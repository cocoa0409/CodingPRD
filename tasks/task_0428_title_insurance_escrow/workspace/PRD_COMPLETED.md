# Title Insurance Escrow API — Product Requirements Document

## 1. Introduction

The Title Insurance Escrow platform is the system of record for a title-insurance underwriter and its escrow-trust operation, modeled on the workflow of a national title insurer and its independent agencies. A single transaction — a home purchase, a refinance, or a reissue — travels through a long pipeline: an order is opened, a title search and examination run against a county plant of recorded instruments, a commitment is issued with its Schedule A estate and its Schedule B exceptions, owner and lender policies are written with endorsements, premium is split between the agency and the underwriter, and escrow funds flow in as deposits and out as wires until the trust ledger balances to zero. Layered on top of that pipeline are the loss-side concerns every title insurer carries: gap coverage between the search date and the recording date, curative work to clear defects, and claims adjudication when an insured loss surfaces after closing.

This document specifies the REST API that orchestrates that pipeline. The system serves three professional constituencies whose responsibilities do not overlap — title agencies that own and operate orders, title officers who produce the title product, and underwriters who price risk and move money — and it must keep each party inside its lane while preserving two hard invariants: that no insurer ever writes coverage over an uncured defect, and that every dollar deposited into escrow is accounted for on its way back out. The requirements below define the entities, their state machines, the premium and reserve mathematics, the escrow-trust accounting rules, and the concurrency and validation discipline that hold those invariants together.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which declares the operational capacity in which the principal is acting. The system recognizes exactly three roles: `Agency`, `TitleOfficer`, and `Underwriter`. A request that is missing either header, or that carries an `X-User-Role` value outside this set, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is authenticated but not permitted for the requested operation is rejected with `ERR_UNAUTHORIZED`.

When `X-User-Role` is `Agency`, `X-User-ID` is the `id` of the acting `Agency` entity. The `Agency` role is entity-backed: ownership checks compare a resource's owning agency to `X-User-ID`. Concretely, an agency may operate only on orders it owns — an order's `agency_id` must equal `X-User-ID` — and the same ownership constraint propagates to every resource reachable through one of those orders (its searches, commitments, exceptions, policies, endorsements, deposits, disbursements, remittances, claims, and curative actions). An agency that attempts to act on an order whose `agency_id` is not its own `X-User-ID` is rejected with `ERR_UNAUTHORIZED`. The `Agency` role is likewise constrained when reading an `Agency` record by id: a `GET` on `/title/agencies/{id}` succeeds only when that `{id}` equals the caller's own `X-User-ID`; reading any other agency's record is rejected with `ERR_UNAUTHORIZED` (the not-found check runs first, so an unknown `{id}` still yields `ERR_NOT_FOUND`). On the collection (list) endpoints — orders and every order-reachable resource — this ownership constraint is applied silently as a filter rather than as a rejection: an `Agency` caller's list is pre-narrowed to resources under its own orders, so resources it does not own are simply omitted from the page (and from `total_count`) rather than triggering an error. The `GET /title/orders` list additionally applies this implicit self-scope even when no `agency_id` query filter is supplied.

When `X-User-Role` is `TitleOfficer`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server accepts it for authentication and audit but does not compare it to any entity's `id`. The same is true when `X-User-Role` is `Underwriter`: `X-User-ID` is an opaque operator identifier with no entity backing, used to authenticate the underwriter but never matched against a stored `id`. Title officers run search and examination, maintain the title plant, issue and re-issue commitments, raise and resolve Schedule B exceptions, drive curative work, and advance the order toward closing; underwriters register agencies, write and void policies and endorsements, post and reverse escrow deposits, approve and wire disbursements, manage premium remittance, and adjudicate claims.

### 2.2. API Response Structure

#### Standard Success Response Format

All successful API responses (those with 2xx status codes) follow this standard envelope format in their JSON body:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z",
    "limit": 10,
    "offset": 0,
    "total_count": 100,
    "has_more": true
  },
  "response_type": "object" | "array",
  "data": { }
}
```

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`.
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits.
- The `response_type` is either "object" for a single resource or "array" for a list of resources.
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field.
- Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints.

#### Standard Error Response Format

All error API responses (4xx status codes) follow this standard envelope format:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z"
  },
  "response_type": "error",
  "data": {
    "error_id": "UNIQUE_ERROR_IDENTIFIER_STRING",
    "message": "A human-readable explanation of the error."
  }
}
```

- The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`.
- The `error_id` is a unique, machine-readable string that identifies the specific error.
- The `message` provides a human-readable explanation of what went wrong.

---

### 2.3. Pagination

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. A supplied `limit` that falls outside `[1, 100]` is clamped into range (values below 1 become 1, values above 100 become 100) rather than rejected; the `offset` parameter is the number of items to skip and defaults to 0, and a negative `offset` is likewise clamped to 0. A `limit` or `offset` that is present but not parseable as an integer is rejected with `ERR_INVALID_REQUEST`.

Unless a specific workflow states otherwise, all list endpoints return their resources sorted by creation timestamp (`created_at`) in ascending order. Because `created_at` is stamped from the logical clock (§3.10), which does not advance on its own per write, many resources can share an identical `created_at`; ties are broken by server-side creation order (the order in which the resources were persisted), so the sort is stable and deterministic.

Every list-based response carries the pagination bookkeeping in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Identity

Every resource is addressed by an `id`, which is a server-minted UUID carrying no type prefix (a bare canonical UUID string with no type-name prefix). Most resources also carry a standard audit triple: `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and `version`, an integer that begins at 1 and increments by one on every mutation. These resource audit timestamps are stamped from the server's logical clock (§3.10), not from host wall-clock time, so before the clock is advanced they read the clock's startup default; this is distinct from the envelope's `api_request_timestamp` (§2.2), which is a wall-clock stamp. `created_at` is fixed at creation; `updated_at` is refreshed on every change, including changes driven by the system rather than by a direct client request on that resource.

One entity is an exception to the audit triple. The `TitlePlantRecord`, which captures an immutable recorded instrument in the county plant, carries only `id` and `created_at`; it has neither `updated_at` nor `version`, because a recorded instrument is never mutated after it is written into the plant. Every other entity — `Agency`, `Order`, `TitleSearch`, `Commitment`, `Exception`, `Policy`, `Endorsement`, `EscrowDeposit`, `Disbursement`, `PremiumRemittance`, `Claim`, and `CurativeAction` — carries the full triple of `created_at`, `updated_at`, and `version`.

Two of those entities additionally expose their `version` as a first-class, client-visible concurrency token used for optimistic concurrency control: the `Policy` and the `Claim` each begin life with `version` equal to 1 and advance it on every mutation. The `Order`'s `version` is likewise client-observable and is the token used by the optimistic-concurrency rules described in §2.7.

### 2.5. Hierarchical Consistency and Cascading State

Many operations in this system mutate more than the resource named in the request. When a parent transitions, the system propagates the change to its children atomically, and each affected resource independently records the mutation by refreshing its `updated_at` and incrementing its `version`. Two cascades recur throughout the workflows and are referenced by name below.

The first, **Cascade A**, fires when an `Order` is cancelled. It unwinds the order's title product in three linked steps. In the first link, every `Commitment` of the order that is in `ISSUED`, `UPDATED`, or `DRAFT` moves to `CANCELLED`. In the second link, each commitment that cancels drives every `Policy` it owns that is in `PENDING` or `ISSUED` to `VOID`. In the third link, each policy that voids reverses its `PremiumRemittance` if that remittance is in `PENDING` or `REMITTED` (moving it to `REVERSED`) and removes every `Endorsement` it owns that is in `REQUESTED` or `ATTACHED` (moving it to `REMOVED`). Cancelling a commitment also voids its open exceptions: every child `Exception` in `RAISED` or `CURATIVE_PENDING` moves to `VOID`, after which the commitment's `open_exception_count` is recomputed.

The second, **Cascade B**, fires when a `Disbursement` is wired. Its first link adds the wired amount to the order's `escrow_disbursed_total_cents` and recomputes `escrow_balance_cents`. Its second link is the auto-close: if that recomputation drives `escrow_balance_cents` to zero while the order is in `CLEAR_TO_CLOSE`, the order transitions itself from `CLEAR_TO_CLOSE` to `CLOSED` without a separate client request, and its `gap_open` flag is set to false.

For any request that targets a nested resource, the system validates path identifiers left to right and rejects the request with `ERR_NOT_FOUND` at the first identifier that does not resolve to an existing resource within scope. A search under a non-existent order, for example, fails on the order before the search is ever consulted.

### 2.6. Monetary Precision and Rounding

All monetary quantities are stored and exchanged as integer cents, and pure aggregations over them — the escrow totals and balance in particular — are exact integer arithmetic with no rounding. Where a calculation introduces a fractional cent (premium tiers scaled by a rate, an endorsement charge taken as a fraction of premium, an agency's retained share of gross premium, or a reserve scaled by a loading factor), the result is rounded to a whole number of cents using the round-half-up convention: a residual of exactly half a cent rounds away from zero to the next whole cent. Each calculation below states the exact point at which rounding is applied, because the order of rounding relative to other operations is part of the contract and is not interchangeable.

### 2.7. Optimistic Concurrency Control on the Escrow Order

Two write operations against an order can advance the order's `version` as a side effect, and both are therefore guarded by optimistic concurrency control so that a client never writes against a stale view of the order. Each of these two creates requires a non-optional `expected_order_version` field in its request body, carrying the `version` of the target `Order` that the client last observed.

The first guarded operation is the creation of a re-issued commitment under an order. The request body must include `expected_order_version`; if it does not equal the order's current `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412). This is the serialization point for the commitment-revision loop: when another writer has already re-issued the commitment and advanced the order's `version`, the current writer's view is stale and its create is refused rather than allowed to supersede a revision it never saw.

The second guarded operation is the creation of a disbursement under an order. Its request body must also carry `expected_order_version`; a value that does not match the order's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412). Because every disbursement create advances the order's `version`, a client whose `expected_order_version` lags behind has not observed a disbursement that already drew down the trust balance, and authorizing a new wire against that outdated balance view is exactly what this check prevents.

No other endpoint takes a version field; operations outside these two creates are not subject to an `expected_order_version` check.

### 2.8. Validation Ordering

When several conditions can independently reject a request, they are evaluated in a fixed priority so that the returned `error_id` is deterministic. Authentication comes first: a request lacking valid headers or carrying an unknown role fails with `ERR_UNAUTHENTICATED`. Authorization is second: a role not permitted for the operation, or an agency reaching for an order it does not own, fails with `ERR_UNAUTHORIZED`. Existence is third: any path- or body-referenced resource that does not resolve within scope fails with `ERR_NOT_FOUND`, with path identifiers checked left to right. Request well-formedness is fourth: a mutating request whose body is missing a required field, carries an invalid enum value, or supplies an out-of-range number fails with `ERR_INVALID_REQUEST`. Optimistic concurrency is fifth: on the two order-scoped creates of §2.7, a mismatched `expected_order_version` fails with `ERR_STALE_VERSION`. State validity is sixth: a transition requested from a state the resource is not currently in fails with `ERR_INVALID_STATE`. Cross-entity referential preconditions are seventh — the prerequisites that depend on another entity's state, such as a policy requiring its commitment to be in `ISSUED`. Title-safety and curative gates are eighth and ninth in the temporal and safety bands. Fiscal checks are evaluated last, after every structural and safety check has passed, so that a money error never masks a safety or state error.

## 3. Business Logic & Workflows

### 3.1. Agencies and the Title Plant

A title `Agency` is the entity-backed principal that owns and operates orders. An underwriter registers an agency by supplying its legal `name` and its `remit_split_pct` — the fraction of gross premium the agency retains on remittance, a number between 0 and 1 inclusive (for example, 0.82 retains 82 percent for the agency and leaves the remainder for the underwriter). A newly registered agency begins in `ACTIVE` `status`. An underwriter may later move an agency between `ACTIVE` and `SUSPENDED` by supplying the desired `to_status`; both directions are permitted and neither carries a precondition. A request whose `to_status` equals the agency's current `status` is a no-op transition and is rejected with `ERR_INVALID_STATE`.

Independently of any single order, title officers maintain the county **title plant**: the chain-of-title record of instruments recorded against parcels. Adding a plant record supplies the `parcel_id` and `county` the instrument was recorded in, the `instrument_type` — one of `DEED`, `MORTGAGE`, `LIEN`, `EASEMENT`, or `RELEASE` — the `recorded_date` (the ISO 8601 UTC date the instrument was recorded into the plant), a `sequence_no` that is the monotonic recording order key on the parcel and must be at least 1, and the conveying and receiving parties as `grantor` and `grantee`. Plant records are immutable reference data and can be listed and filtered by `parcel_id` to walk a parcel's chain of title. The one circumstance under which adding a plant record is refused is a gap defect, described with the gap window in §3.3.

### 3.2. Opening and Advancing an Order

An `Agency` opens an `Order` by supplying the `agency_id` (which must equal its own `X-User-ID`), the `parcel_id` and `county` under order, the `transaction_type` — `PURCHASE`, `REFINANCE`, or `REISSUE` — and the two coverage bases in cents: `sales_price_cents`, the purchase price that anchors owner coverage and may be 0 for a pure refinance, and `loan_amount_cents`, the loan that anchors lender coverage and is 0 when there is no lender policy. Both amounts must be non-negative. The supplied `agency_id` must resolve to an existing `Agency`; an unknown `agency_id` is rejected with `ERR_NOT_FOUND`, and this existence check is evaluated before the self-ownership check, so a well-formed request naming a non-existent agency yields `ERR_NOT_FOUND` while a request naming a real but different agency yields `ERR_UNAUTHORIZED`. A new order opens in `OPENED` `status`, with its escrow figures at zero and `gap_open` false. The order also exposes three computed escrow figures, defined in §3.7: `escrow_deposit_total_cents`, `escrow_disbursed_total_cents`, and `escrow_balance_cents`.

The order advances through a fixed production sequence: `OPENED` → `IN_TITLE` → `COMMITTED` → `CLEAR_TO_CLOSE` → `CLOSED`, with `CANCELLED` reachable from any non-terminal state. A title officer moves an order from `OPENED` to `IN_TITLE` once at least one `TitleSearch` exists for it in `ORDERED` or `IN_EXAM`. The step from `IN_TITLE` to `COMMITTED` carries two cross-entity preconditions: the order must have a `Commitment` in `ISSUED` (otherwise `ERR_NO_ISSUED_COMMITMENT`), and it must have a `TitleSearch` in `COMPLETED` whose `chain_verified` is true (otherwise `ERR_CHAIN_NOT_VERIFIED`). The step from `COMMITTED` to `CLEAR_TO_CLOSE` carries two more: the order's `ISSUED` commitment must have an `open_exception_count` of 0 — every exception waived or cleared — (otherwise `ERR_EXCEPTIONS_OPEN`), and the order must have at least one `Policy` in `ISSUED` (otherwise `ERR_NO_ISSUED_POLICY`). The final step from `CLEAR_TO_CLOSE` to `CLOSED` requires that `escrow_balance_cents` be exactly 0 — every deposited dollar disbursed — (otherwise `ERR_ESCROW_NOT_ZERO`); on closing, `gap_open` is set false because recording is complete and the gap window has shut. This close may be requested explicitly by a title officer, or it may happen automatically as the second link of Cascade B when a wire drives the balance to zero, as described in §2.5 and §3.7.

Cancellation is the `Agency`'s prerogative and is available from `OPENED`, `IN_TITLE`, or `COMMITTED`. In every case the order's `escrow_balance_cents` must be 0 before it can be cancelled (otherwise `ERR_ESCROW_NOT_ZERO`), so that no posted trust funds are stranded. Cancellation from `IN_TITLE` or from `COMMITTED` additionally fires Cascade A, unwinding commitments, policies, remittances, endorsements, and exceptions as detailed in §2.5; cancellation from `OPENED` has no children to unwind and simply terminates the order. `CLOSED` and `CANCELLED` are terminal.

### 3.3. Search, Examination, and the Gap Window

A title officer orders a `TitleSearch` under an order by supplying the `searched_parcel_id` (copied from the order's parcel) and an `effective_date`, the ISO 8601 UTC date that marks the start of the insured gap window. The search opens in `ORDERED`. The examiner advances it to `IN_EXAM` and finally to `COMPLETED`. From either `ORDERED` or `IN_EXAM` the search may instead be cancelled to `CANCELLED`, which is terminal alongside `COMPLETED`.

Completing the search is where the gap window is recorded. The transition to `COMPLETED` requires the request to supply `chain_verified`, `gap_from_date`, and `gap_to_date`, and `gap_from_date` must be less than or equal to `gap_to_date` (otherwise `ERR_INVALID_GAP_WINDOW`). The supplied `chain_verified` flag — true when the chain of title walked from the plant is unbroken — and the two dates are persisted on the search; `gap_from_date` is the inclusive start of the uninsured gap window (equal to the `effective_date`) and `gap_to_date` is its inclusive end (the expected recording date). Completing the search also sets the parent order's `gap_open` flag to true: the uninsured gap window has opened, and from this moment gap-defect checks apply to the parcel. The `gap_open` flag returns to false only when the order closes or cancels.

While an order is `gap_open`, the title plant is policed for **gap defects**. When a title officer attempts to add a plant record whose `instrument_type` is `LIEN` or `MORTGAGE`, the system checks the new record's `recorded_date` against the closed gap window `[gap_from_date, gap_to_date]` of every `COMPLETED` search on the same parcel whose order is still `gap_open`. The gap window here is a closed interval: a `recorded_date` falling on `gap_from_date`, on `gap_to_date`, or anywhere between them lands inside the window. If the new lien or mortgage falls inside any such active gap window, the record is rejected with `ERR_GAP_DEFECT`, because it represents an encumbrance recorded during the uninsured gap that the policy would otherwise have to insure over. Other instrument types, and liens or mortgages recorded outside every active gap window, are accepted.

### 3.4. Commitments, Schedule A, and the Revision Loop

A `Commitment` realizes the insurer's promise to insure a particular estate. A title officer issues one under an order by supplying the `effective_date` that starts the commitment window, the `expiry_date` that ends it, the `schedule_a_estate` — `FEE_SIMPLE` or `LEASEHOLD` — and the `insured_amount_cents`, the Schedule A insured amount that is the ceiling for owner-policy coverage and must be greater than 0. The commitment window is half-open: the interval runs from `effective_date` up to but not including `expiry_date`. A commitment is born in `DRAFT` and exposes two computed fields: `open_exception_count`, the number of its child exceptions whose `status` is `RAISED` or `CURATIVE_PENDING`, and `revision_no`, the number of times it has been re-issued, which starts at 0.

A commitment moves from `DRAFT` to `ISSUED` only when no other commitment on the same order is currently `ISSUED`; the system keeps at most one `ISSUED` commitment per order, and a violation is reported as `ERR_INVALID_STATE`. The system supports a **revision loop** so a commitment can be amended without losing its history. Creating a new commitment under an order that already has an `ISSUED` commitment supersedes the prior one: the prior `ISSUED` commitment flips to `UPDATED`, its `revision_no` is incremented by 1, and the order's `version` is incremented by 1 (the parent bump that backs the optimistic-concurrency rule of §2.7). A superseded commitment in `UPDATED` can later be re-issued back to `ISSUED` — again only when no other commitment on the same order is currently `ISSUED`, else `ERR_INVALID_STATE` — closing the loop. This re-issue create is the operation guarded by `expected_order_version`; see §2.7 for the stale-version rejection.

A commitment in `ISSUED` may expire. The transition to `EXPIRED` is permitted only once the logical clock has reached or passed the commitment's `expiry_date` (otherwise `ERR_COMMITMENT_NOT_EXPIRABLE`); on expiry, every child `Exception` in `RAISED` or `CURATIVE_PENDING` is voided. A commitment can also reach `CANCELLED`, but only as a system step inside Cascade A when its order is cancelled; that cancellation voids the commitment's open exceptions and drives its policies to `VOID` as described in §2.5. `EXPIRED` and `CANCELLED` are terminal.

### 3.5. Schedule B Exceptions and Curative

Schedule B of a commitment lists the **exceptions** — the matters the policy will not insure unless they are first disposed of. A title officer raises one against a commitment by supplying its `exception_type` — `STANDARD` for a pre-printed Schedule B-I item, `SPECIAL` for a B-II specific defect, or `SUBORDINATE_LIEN` — a free-text `description`, and an optional `curative_required` flag (defaulting to false) that marks an exception which must pass through curative before it can clear. A raised exception is in `RAISED`, and raising it recomputes the parent commitment's `open_exception_count`.

An exception leaves `RAISED` along one of two paths. It may be **waived** straight to `WAIVED`, but only if `curative_required` is false; a curative-required exception cannot be waived and the attempt is rejected with `ERR_CURATIVE_REQUIRED`. Alternatively it may be moved to `CURATIVE_PENDING` to enter curative work. From `CURATIVE_PENDING` it can be **cleared** to `CLEARED`, but only once a `CurativeAction` whose `subject_type` is `EXCEPTION` and whose `subject_id` is this exception exists in `RESOLVED` status (otherwise `ERR_NO_RESOLVED_CURATIVE`). If curative fails, the exception reverts from `CURATIVE_PENDING` back to `RAISED`. Every transition into `WAIVED`, `CLEARED`, `VOID`, or back to `RAISED` recomputes the parent commitment's `open_exception_count`, because that count is what gates policy issuance and the move to `CLEAR_TO_CLOSE`. `WAIVED`, `CLEARED`, and `VOID` are terminal; an exception reaches `VOID` only through a system cascade when its commitment expires or is cancelled.

Curative work itself is tracked as a `CurativeAction`, opened under an order against either an exception or a claim. The creator supplies a `subject_type` of `EXCEPTION` or `CLAIM`, a `subject_id` that resolves to an `Exception` when the subject type is `EXCEPTION` and to a `Claim` when it is `CLAIM`, and an `action_type` — `PAYOFF`, `RELEASE_FILED`, `QUIET_TITLE`, or `INDEMNITY`. The `subject_id` is resolved purely by id against the relevant entity collection — to any existing `Exception` (for `EXCEPTION`) or any existing `Claim` (for `CLAIM`) — and is not constrained to live under the same order the curative action is opened on; a `subject_id` that matches no such entity is rejected with `ERR_NOT_FOUND`. A curative action opens in `OPEN`. A title officer or underwriter resolves it to `RESOLVED`, which is what unblocks the dependent exception-clear or claim-pay precondition for the cited subject, or abandons it to `ABANDONED`. Both `RESOLVED` and `ABANDONED` are terminal.

### 3.6. Policies, Premium, and Endorsements

Once a commitment is in hand, an underwriter creates a `Policy` under the order, tying it to the commitment by supplying the `commitment_id`, the `policy_type` — `OWNER`, whose coverage basis is the sales price, or `LENDER`, whose basis is the loan amount — and the `coverage_amount_cents`, which must be greater than 0. The supplied `commitment_id` must resolve to a commitment that exists and belongs to this same order; a `commitment_id` that is unknown or that names a commitment under a different order is rejected with `ERR_NOT_FOUND` (this existence-within-scope check is part of the left-to-right path/body resolution of §2.5 and runs before any state or fiscal check on the policy). Two optional flags shape pricing: `is_reissue` (default false) marks a policy that qualifies for the reissue/refi rate because a qualifying prior policy exists within the reissue window, and `co_issued_with_owner` (default false), meaningful only for a lender policy, marks a lender policy co-issued together with an owner policy on the same order. A new policy is in `PENDING` with `version` 1. Although the request may carry a coverage figure, the premium itself is not client-supplied: `gross_premium_cents` is computed at issuance and any input value for it is ignored.

Issuing a policy — the move from `PENDING` to `ISSUED` — is the underwriter's act and carries three preconditions, checked against the policy's commitment. The commitment must be in `ISSUED` (otherwise `ERR_COMMITMENT_NOT_ISSUED`); the commitment's `open_exception_count` must be 0 (otherwise `ERR_EXCEPTIONS_OPEN`); and the policy's `coverage_amount_cents` must not exceed the commitment's `insured_amount_cents` (otherwise `ERR_COVERAGE_EXCEEDS_COMMITMENT`). When those pass, two things happen atomically: the premium is computed and frozen into `gross_premium_cents`, and a `PremiumRemittance` is created in `PENDING` carrying the split snapshot described in §3.8.

**Premium for an owner policy** is tiered on the coverage expressed in dollars (the `coverage_amount_cents` divided by 100). The first 100,000 dollars of coverage are priced at 5.00 dollars per 1,000 dollars; the portion of coverage above 100,000 dollars and up to 500,000 dollars is priced at 4.00 dollars per 1,000 dollars; and any coverage above 500,000 dollars is priced at 3.00 dollars per 1,000 dollars. Each band contributes its dollar amount divided by 1,000, multiplied by that band's per-thousand rate; the three contributions are summed to a base, which is then converted from dollars to cents by multiplying by 100. For a standard owner policy (`is_reissue` false) that un-rounded base in cents is rounded half-up to whole cents to give `gross_premium_cents`. For a reissue owner policy (`is_reissue` true), the un-rounded base in cents is first multiplied by the reissue factor of 0.60 and only then rounded half-up to whole cents — the factor is applied to the un-rounded base and the rounding happens exactly once, which yields a strictly lower premium than the standard rate for identical coverage.

**Premium for a lender policy** begins from the same tiered base — the identical 5.00, 4.00, and 3.00 per-thousand bands computed on the lender policy's `coverage_amount_cents`, with no reissue factor. For a standalone lender policy (`co_issued_with_owner` false) that tiered base in cents is rounded half-up to whole cents to give `gross_premium_cents`. For a co-issued lender policy (`co_issued_with_owner` true), the premium is instead a flat 2,500 cents regardless of the tiered base; the owner policy is priced first and the lender policy is then written at this flat co-issue rate.

An underwriter may attach **endorsements** to a policy. Requesting an endorsement supplies the ALTA `form_code` — `ENV_PROTECTION`, `ZONING`, `SURVEY`, or `RESTRICTIONS` — and a `charge_pct`, the charge expressed as a fraction of the policy's gross premium, which must be greater than 0 and at most 1. The endorsement opens in `REQUESTED`. Attaching it — the move to `ATTACHED` — is permitted only while the parent policy is in `ISSUED` (otherwise `ERR_POLICY_NOT_ISSUED`); on attachment the system computes `charge_cents` as the policy's `gross_premium_cents` multiplied by `charge_pct`, rounded half-up to whole cents. An attached endorsement can later be removed to `REMOVED`, which is also where every endorsement lands when its policy is voided under Cascade A. `REMOVED` is terminal.

A policy is voided by the underwriter from `ISSUED`, or by the system as the second link of Cascade A. A direct void is blocked while any claim under the policy is in `INVESTIGATING` or `CURATIVE` (otherwise `ERR_POLICY_HAS_OPEN_CLAIM`). When a policy voids, the third link of Cascade A runs: its `PremiumRemittance` in `PENDING` or `REMITTED` is reversed to `REVERSED`, and every `Endorsement` in `REQUESTED` or `ATTACHED` is removed. `VOID` is terminal.

### 3.7. Escrow Trust Accounting: Deposits, Disbursements, and Wires

The escrow side of the order is a trust ledger that must always reconcile. Incoming funds are recorded as an `EscrowDeposit` under the order, supplying the `amount_cents` (greater than 0) and a `source_ref`, the external wire or check reference for the funds. A deposit opens in `RECEIVED`. An underwriter posts it to `POSTED`, and only at that point does it count toward the trust balance; a posted deposit may later be reversed to `REVERSED` as a compensating action, but a reversal is refused if it would drive `escrow_balance_cents` below zero (`ERR_ESCROW_WOULD_GO_NEGATIVE`). A deposit still in `RECEIVED` may be reversed directly with no balance consequence. Posting or reversing a deposit recomputes the order's escrow totals.

Outgoing funds are an `Disbursement` requested under the order, supplying the `payee`, the `amount_cents` (greater than 0), the `purpose` — `SELLER_PROCEEDS`, `PAYOFF`, `PREMIUM`, `RECORDING_FEE`, or `CLAIM_PAYOUT` — and the bank wire reservation, given as `wire_window_start` and `wire_window_end`. That reservation is a half-open interval running from `wire_window_start` inclusive up to `wire_window_end` exclusive. A disbursement opens in `REQUESTED`. Its create is the second order-scoped operation guarded by `expected_order_version` and bumps the order's `version`; see §2.7. An underwriter approves it to `APPROVED`, then wires it to `WIRED`. Approval requires the order to be in a disbursable state: for every purpose other than `CLAIM_PAYOUT` the order must be in `CLEAR_TO_CLOSE` or `CLOSED`, while a `CLAIM_PAYOUT` is allowed only when the order is `CLOSED` (otherwise `ERR_ORDER_NOT_DISBURSABLE`). A disbursement in `REQUESTED` or `APPROVED` may instead be voided to `VOID`.

Wiring a disbursement — the move from `APPROVED` to `WIRED` — carries two preconditions. The `amount_cents` must be less than or equal to the order's current `escrow_balance_cents` (otherwise `ERR_INSUFFICIENT_ESCROW`), and the disbursement's half-open wire window — from `wire_window_start` inclusive to `wire_window_end` exclusive — must not overlap the window of any other `WIRED` disbursement on the same order (otherwise `ERR_WIRE_WINDOW_OVERLAP`). Because the wire windows are half-open, two windows that are exactly adjacent — one ending at the instant the next begins — do not overlap and are both allowed; only windows that share an interior instant collide. A successful wire fires Cascade B: `escrow_disbursed_total_cents` grows by the wired `amount_cents`, `escrow_balance_cents` is recomputed, and if the balance reaches zero while the order is in `CLEAR_TO_CLOSE`, the order auto-transitions to `CLOSED` with `gap_open` set false, as described in §2.5. Only `WIRED` disbursements reduce the balance; `WIRED` and `VOID` are terminal.

The three computed escrow figures on the order are pure aggregations, recomputed whenever a deposit or disbursement changes state. `escrow_deposit_total_cents` is the sum of `amount_cents` across the order's deposits in `POSTED`. `escrow_disbursed_total_cents` is the sum of `amount_cents` across the order's disbursements in `WIRED`. `escrow_balance_cents` is the deposit total minus the disbursed total, in exact integer cents — the live trust balance the close, cancel, reversal, and wire checks all read.

### 3.8. Premium Remittance and the Split

Every issued policy carries a `PremiumRemittance`, created in `PENDING` at the moment the policy is issued, that records how the gross premium is divided between the agency and the underwriter. The remittance snapshots the policy's `gross_premium_cents` at creation (its own `gross_premium_cents` is this frozen copy) and derives the split in a pinned order. The agency's share, `agency_retained_cents`, is the snapshotted `gross_premium_cents` multiplied by the owning agency's `remit_split_pct`, rounded half-up to whole cents. The underwriter's share, `underwriter_remit_cents`, is then the gross minus the agency-retained amount. Rounding the agency share first and deriving the underwriter share by subtraction is deliberate and is part of the contract: it guarantees that `agency_retained_cents` plus `underwriter_remit_cents` equals the gross with zero drift, which independently rounding both halves would not.

An underwriter remits a `PENDING` remittance to `REMITTED`, but only while the parent policy is in `ISSUED` (otherwise `ERR_POLICY_NOT_ISSUED`). A remittance in `PENDING` or `REMITTED` is reversed to `REVERSED` only as a system step in the third link of Cascade A when its policy voids; the conservation identity that the agency-retained and underwriter-remitted amounts sum to the gross is unwound atomically on reversal, so the split never drifts. `REVERSED` is terminal.

### 3.9. Claims and Adjudication

A claim is brought under an issued policy, and like every endorsement, remittance, and claim, it carries the `policy_id` of the policy it hangs from — established by the policy under which it is filed rather than by a client-supplied key. An underwriter files one — first notice of loss — by supplying the `claim_type` — `UNDISCLOSED_LIEN`, `BOUNDARY_DISPUTE`, `FORGERY`, or `ACCESS_DEFECT` — and the adjuster's `estimated_loss_cents`, which must be non-negative and serves as the reserve basis. A claim opens in `FNOL` with `version` 1, and exposes a computed `reserve_cents`, a `settled_loss_cents` that defaults to 0 until settlement, and a computed `paid_cents`.

The claim's machine is a loop. From `FNOL` the underwriter moves it to `INVESTIGATING`, which is permitted only while the parent policy is in `ISSUED` (otherwise `ERR_POLICY_NOT_ISSUED`) and which sets the provisional reserve: `reserve_cents` is the `estimated_loss_cents` multiplied by the loss-loading factor of 1.15 (covering defense and curative cost), rounded half-up to whole cents and then capped so that it never exceeds the parent policy's `coverage_amount_cents`. From `INVESTIGATING` the claim can move to `CURATIVE` to pursue a cure and can loop back from `CURATIVE` to `INVESTIGATING` when curative is inconclusive, as many times as needed. From `INVESTIGATING` the claim can be denied to `DENIED`, which releases the reserve by setting `reserve_cents` to 0.

A claim is paid only from `CURATIVE`. The move to `PAID` requires that a `CurativeAction` whose `subject_type` is `CLAIM` and whose `subject_id` is this claim exists in `RESOLVED` (otherwise `ERR_NO_RESOLVED_CURATIVE`), and the request must supply `settled_loss_cents`, the final settled loss. On payment, `paid_cents` is set to the lesser of the supplied `settled_loss_cents` and the parent policy's `coverage_amount_cents` — the actual settled loss with no loading factor, capped at coverage — and `reserve_cents` is released to 0. The provisional reserve and the final payout are deliberately different numbers on the same claim: the reserve is a loaded estimate held open during investigation, while the payout is the unloaded settled figure capped at coverage. `PAID` and `DENIED` are terminal. A claim payout reaches the payee through escrow as a `CLAIM_PAYOUT` disbursement, which §3.7 confines to an order already in `CLOSED`.

### 3.10. The Logical Clock

To make commitment expiry and gap windows deterministic under test, the system runs on a logical clock rather than wall-clock time. The clock's startup default is `2026-01-01T00:00:00Z`; before any clock has been set, every time-dependent check reads exactly this default and never falls back to the host's real time. A title officer or underwriter advances the clock by supplying a `to_iso8601` instant. The expiry precondition of §3.4 — that a commitment may move to `EXPIRED` only once the clock has reached or passed its `expiry_date` — is evaluated against this logical clock.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that read a resource, list a collection, or transition an existing resource's state return `200 OK`. Every mutating request is subject to the validation ordering of §2.8, and the request and response bodies for each operation are reconstructed from the workflow narratives in §3 rather than restated here.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/title/agencies` | Register a title agency | Underwriter |
| GET | `/title/agencies/{id}` | Get an agency | Underwriter, Agency |
| POST | `/title/agencies/{id}/transitions` | Suspend or reactivate an agency | Underwriter |
| POST | `/title/plant-records` | Add a recorded instrument to the title plant | TitleOfficer |
| GET | `/title/plant-records/{id}` | Get a single plant record | TitleOfficer, Underwriter |
| GET | `/title/plant-records` | List plant records, filterable by `parcel_id` | TitleOfficer, Underwriter |
| POST | `/title/orders` | Open a new title order | Agency |
| GET | `/title/orders/{id}` | Get an order, including computed escrow figures | Agency, TitleOfficer, Underwriter |
| GET | `/title/orders` | List orders, filterable by `agency_id` and `status` | Agency, TitleOfficer, Underwriter |
| POST | `/title/orders/{id}/transitions` | Transition an order; cancel fires Cascade A; close requires a zero escrow balance | Agency, TitleOfficer |
| POST | `/title/orders/{id}/title-searches` | Order a title search/exam under an order | TitleOfficer |
| GET | `/title/orders/{id}/title-searches` | List title searches for an order | TitleOfficer, Underwriter, Agency |
| GET | `/title/title-searches/{id}` | Get a title search | TitleOfficer, Underwriter |
| POST | `/title/title-searches/{id}/transitions` | Transition a title search; completion persists the chain flag and gap window | TitleOfficer |
| POST | `/title/orders/{id}/commitments` | Issue or re-issue a commitment under an order | TitleOfficer |
| GET | `/title/orders/{id}/commitments` | List commitments for an order, filterable by `status` | TitleOfficer, Underwriter, Agency |
| GET | `/title/commitments/{id}` | Get a commitment | TitleOfficer, Underwriter, Agency |
| POST | `/title/commitments/{id}/transitions` | Transition a commitment (issue, re-issue, expire) | TitleOfficer |
| POST | `/title/commitments/{id}/exceptions` | Raise a Schedule B exception on a commitment | TitleOfficer |
| GET | `/title/commitments/{id}/exceptions` | List exceptions for a commitment, filterable by `status` | TitleOfficer, Underwriter, Agency |
| GET | `/title/exceptions/{id}` | Get an exception | TitleOfficer, Underwriter |
| POST | `/title/exceptions/{id}/transitions` | Transition an exception (waive, curative, clear, revert) | TitleOfficer |
| POST | `/title/orders/{id}/policies` | Create an owner or lender policy tied to a commitment | Underwriter |
| GET | `/title/policies` | List policies, filterable by `order_id`, `commitment_id`, and `status` | Underwriter, TitleOfficer, Agency |
| GET | `/title/policies/{id}` | Get a policy | Underwriter, TitleOfficer, Agency |
| POST | `/title/policies/{id}/transitions` | Transition a policy; issue computes premium and creates a remittance; void fires Cascade A link 3 | Underwriter |
| POST | `/title/policies/{id}/endorsements` | Request an endorsement on a policy | Underwriter |
| GET | `/title/policies/{id}/endorsements` | List endorsements for a policy, filterable by `status` | Underwriter, TitleOfficer, Agency |
| GET | `/title/endorsements/{id}` | Get an endorsement | Underwriter, TitleOfficer |
| POST | `/title/endorsements/{id}/transitions` | Transition an endorsement; attach computes the charge | Underwriter |
| POST | `/title/orders/{id}/deposits` | Record an incoming escrow deposit on an order | Agency, Underwriter |
| GET | `/title/orders/{id}/deposits` | List deposits for an order, filterable by `status` | Agency, Underwriter, TitleOfficer |
| GET | `/title/deposits/{id}` | Get a deposit | Agency, Underwriter |
| POST | `/title/deposits/{id}/transitions` | Transition a deposit (post, reverse) | Underwriter |
| POST | `/title/orders/{id}/disbursements` | Request an outgoing wire against the order escrow | Underwriter |
| GET | `/title/orders/{id}/disbursements` | List disbursements for an order, filterable by `status` | Underwriter, Agency, TitleOfficer |
| GET | `/title/disbursements/{id}` | Get a disbursement | Underwriter, Agency |
| POST | `/title/disbursements/{id}/transitions` | Transition a disbursement (approve, wire, void); wire fires Cascade B | Underwriter |
| GET | `/title/policies/{id}/remittances` | List premium remittances for a policy, filterable by `status` | Underwriter, Agency |
| GET | `/title/remittances/{id}` | Get a premium remittance | Underwriter, Agency |
| POST | `/title/remittances/{id}/transitions` | Transition a remittance (remit) | Underwriter |
| POST | `/title/policies/{id}/claims` | File a claim under an issued policy | Underwriter |
| GET | `/title/policies/{id}/claims` | List claims for a policy, filterable by `status` | Underwriter, Agency |
| GET | `/title/claims/{id}` | Get a claim | Underwriter, Agency |
| POST | `/title/claims/{id}/transitions` | Transition a claim (investigate, curative loop, deny, pay) | Underwriter |
| POST | `/title/orders/{id}/curative-actions` | Open a curative action against an exception or a claim | TitleOfficer, Underwriter |
| GET | `/title/orders/{id}/curative-actions` | List curative actions for an order, filterable by `subject_type`, `subject_id`, and `status` | TitleOfficer, Underwriter, Agency |
| GET | `/title/curative-actions/{id}` | Get a curative action | TitleOfficer, Underwriter |
| POST | `/title/curative-actions/{id}/transitions` | Transition a curative action (resolve, abandon) | TitleOfficer, Underwriter |
| POST | `/title/_clock/set_current_utc` | Advance the server logical clock | TitleOfficer, Underwriter |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_INVALID_GAP_WINDOW` | 422 Unprocessable Entity |
| `ERR_NO_ISSUED_COMMITMENT` | 409 Conflict |
| `ERR_CHAIN_NOT_VERIFIED` | 409 Conflict |
| `ERR_EXCEPTIONS_OPEN` | 409 Conflict |
| `ERR_NO_ISSUED_POLICY` | 409 Conflict |
| `ERR_COMMITMENT_NOT_ISSUED` | 409 Conflict |
| `ERR_COVERAGE_EXCEEDS_COMMITMENT` | 409 Conflict |
| `ERR_COMMITMENT_NOT_EXPIRABLE` | 409 Conflict |
| `ERR_GAP_DEFECT` | 409 Conflict |
| `ERR_POLICY_NOT_ISSUED` | 409 Conflict |
| `ERR_POLICY_HAS_OPEN_CLAIM` | 409 Conflict |
| `ERR_CURATIVE_REQUIRED` | 409 Conflict |
| `ERR_NO_RESOLVED_CURATIVE` | 409 Conflict |
| `ERR_ORDER_NOT_DISBURSABLE` | 409 Conflict |
| `ERR_INSUFFICIENT_ESCROW` | 409 Conflict |
| `ERR_WIRE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_ESCROW_WOULD_GO_NEGATIVE` | 409 Conflict |
| `ERR_ESCROW_NOT_ZERO` | 409 Conflict |
