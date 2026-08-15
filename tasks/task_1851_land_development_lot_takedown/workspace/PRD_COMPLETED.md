# Land Development & Lot Takedown API — Product Requirements Document

## 1. Introduction

Residential land development runs on a long chain of contingent commitments: a developer ties up a raw parcel while entitlements are worked out, plats the land into phases and lots, bonds the infrastructure the county requires, and then feeds finished lots to homebuilders under takedown agreements whose prices drift upward over time. Every link in that chain is finite and contested — lots are recorded inventory that can be reserved exactly once, the development loan is a fixed commitment that draws and lien-release payments compete for, and the homeowners association eventually wrests control from the declarant once enough lots have closed. This document specifies the API that manages that entire pipeline, from parcel acquisition under an entitlement contingency through final lot sellout and HOA transition.

The system serves five distinct operator populations — the developer's own staff, builder representatives, lender officers, municipal clerks, and HOA managers — with strict segregation of duties between them: the person who requests a loan draw may never approve it, and the clerk who certifies infrastructure acceptance may never post or release the bond. A single logical clock governs all deadline, escalator, and absorption computations so that time-based behavior is deterministic and testable. All resources are exposed flat under the `/api` mount point and cross-reference one another by identifier rather than by nested URLs.

## 2. Global Specifications & System-Wide Principles

This section defines the contract-level rules that apply uniformly across the API: authentication, response envelopes, pagination, resource identity, the logical clock, monetary precision, optimistic concurrency, validation ordering, and the conservation invariants the server maintains.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the operational capacity in which they act. The declared role names are `DeveloperOperator`, `BuilderRep`, `LenderOfficer`, `MunicipalClerk`, and `HOAManager`. A request whose `X-User-Role` does not name one of these five roles, or whose `X-User-ID` is absent, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is not permitted for the target endpoint — or that fails an entity-backed ownership check — is rejected with `ERR_FORBIDDEN_ROLE`.

Two roles are entity-backed, which ties the header value to persisted resources. When `X-User-Role` is `BuilderRep`, `X-User-ID` is the `id` of the acting `Builder`; ownership checks on any resource that references a builder compare the takedown agreement's `builder_id` to `X-User-ID`, so a builder representative may reserve lots, open closings, cancel closings, or amend pricing terms only under their own builder's agreements. When `X-User-Role` is `HOAManager`, `X-User-ID` is the `id` of the acting `HOAAssociation`; ownership checks compare the association's own `id` to `X-User-ID`, so a manager may evaluate or complete the control transition only for their own association. The remaining three roles are opaque operator identifiers: when `X-User-Role` is `DeveloperOperator`, `LenderOfficer`, or `MunicipalClerk`, `X-User-ID` is not tied to any persisted entity; the server may record it (for example, as `requested_by_user_id` on a `LoanDraw` or `approved_by_user_id` once the draw is approved) but never compares it to any entity's `id`.

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

### 2.3. Pagination

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and is capped at a maximum of 100. The `offset` parameter sets how many items to skip and defaults to 0. Both parameters must be integers; a non-integer value, a `limit` outside 1 through 100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` — an out-of-range `limit` is rejected, not clamped. All list endpoints return resources sorted by creation timestamp in ascending order, and every list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope, where `has_more` is true exactly when `offset` plus the number of items on the returned page is less than `total_count`. Several list endpoints additionally accept domain filters — the parcel list filters by `status`; the phase list by `parcel_id` and `status`; the bond list by `phase_id` and `status`; the agreement list by `parcel_id`, `builder_id`, and `status`; the lot list by `phase_id`, `sales_status`, `lien_status`, and `reserved_agreement_id`; the closing list by `lot_id`, `agreement_id`, `loan_id`, and `status`; the loan list by `parcel_id` and `status`; the draw list by `loan_id` and `status`; the HOA list by `parcel_id` and `status`; the provider list by `utility_type`; and the connection list by `lot_id`, `provider_id`, and `status`.

### 2.4. Common Resource Properties

Every resource in the system — `Parcel`, `Phase`, `InfrastructureBond`, `Builder`, `TakedownAgreement`, `Lot`, `LotClosing`, `DevelopmentLoan`, `LoanDraw`, `HOAAssociation`, `UtilityProvider`, and `UtilityConnection` — carries a standard set of system-managed properties:

- `id` (string): a server-minted UUID with no type prefix, assigned at creation.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that starts at 1 on creation and increments by exactly one on every mutation.

Recomputation of a derived field counts as a mutation: when a lot reservation changes a parcel's `lots_available_count`, or a closing finalize changes a loan's `outstanding_balance_cents`, the affected parent resource's `updated_at` refreshes and its `version` increments by one, independently of whatever happened to the child. Within a single request, an entity touched by several links of the same cascade is mutated once — its `updated_at` refreshes once and its `version` increments by exactly one for that request, however many links affected it. There are no exceptions to the common-property set in this system; every entity above carries all four fields.

### 2.5. The Logical Clock and Time-Driven Transitions

The server maintains a single logical clock that governs every deadline check, escalator computation, impact-fee indexation, and trailing absorption window. Every ISO 8601 instant supplied in a request body is normalized to UTC at whole-second precision before storage and before any comparison against the clock. At startup the clock reads exactly `2026-08-01T00:00:00Z`; before any explicit set call it holds that fixed instant and never consults the wall clock. A `DeveloperOperator`-only test-driving capability advances the clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`; the set accepts any parseable instant, earlier or later than the current value, and moving the clock backward never reverses a transition that has already fired.

Advancing the clock is not a passive read operation. Any parcel sitting in `CONTINGENCY_ACTIVE` whose `contingency_end_date` falls strictly before the new clock value auto-transitions to `TERMINATED`, with its earnest money forfeited (see §3.1), and every parcel's trailing absorption windows re-anchor to the new instant (see §3.8), with the recompute mutating a parcel only when a derived value actually moves (see §2.9). Because the deadline is inclusive, setting the clock to exactly the contingency deadline does not trigger expiry — only a value strictly past it does.

### 2.6. Monetary Precision and Rounding Discipline

All monetary amounts in the system are integer numbers of cents; there are no fractional-cent values anywhere in requests, responses, or stored state. Percentages and rates are likewise carried as integer basis points (ten-thousandths of a whole), so a five-percent retainage travels as 500 and a one-hundred-ten-percent bond multiplier as 11000.

Whenever a calculation must produce an integer-cent result from a fractional intermediate, the system rounds half-up — a discarded fraction of exactly one-half rounds away from zero. Where a calculation chains multiple rounded steps, the rounding order is pinned by the business rule and stated alongside it (the draw disbursement in §3.6 is the canonical example: retainage is rounded first from the gross, the fee second from the post-retainage base). Non-monetary derived quantities use their own stated precision: absorption paces are rounded half-up to four decimal places, the sellout projection to one decimal place, and the parcel's closed percentage to two decimal places.

### 2.7. Optimistic Concurrency Control

Two write operations in the system are guarded by optimistic concurrency control, and only those two carry an expected-version input field.

Extending a parcel's contingency requires the request to carry `expected_parcel_version` holding the client's last observed `version` of the target `Parcel`. If the parcel's current `version` has advanced beyond what the client observed — because a prior extension or any other parcel mutation superseded the client's view of the deadline — the extension is rejected with `ERR_STALE_PARCEL_VERSION` (HTTP 412).

Amending a takedown agreement's pricing terms requires the request to carry `expected_agreement_version` holding the client's last observed `version` of the target `TakedownAgreement`. If the agreement's current `version` has advanced since that observation — because a prior amendment or any cascade touching the agreement superseded the client's view of the pricing terms — the amendment is rejected with `ERR_STALE_AGREEMENT_VERSION` (HTTP 412).

Both fields are non-optional on their respective operations; the request is malformed without them. No other endpoint in the system accepts or requires a version field.

### 2.8. Validation Order and Resource Resolution

Requests are screened against a fixed, ordered validation cascade so that the same failure always surfaces as the same error, regardless of how many rules it would violate. The order is:

1. **Authentication** — the headers of §2.1 must be present and the role declared; violations yield `ERR_UNAUTHENTICATED` (401).
2. **Role authorization and ownership** — the role must be permitted for the endpoint and, for entity-backed roles, the ownership check of §2.1 must pass; violations yield `ERR_FORBIDDEN_ROLE` (403). An ownership check is evaluated whenever the resource it reads resolves — whether the path target or the agreement referenced in the request body; an unresolvable reference cannot be ownership-checked and falls through to the priority-3 existence check, which then supplies the 404.
3. **Resource existence** — path identifiers are resolved first, in left-to-right order, followed by foreign keys carried in the request body (`parcel_id`, `builder_id`, `phase_id`, `lot_id`, `agreement_id`, `loan_id`, `provider_id`). The first unresolvable reference short-circuits the request with the matching not-found error: `ERR_PARCEL_NOT_FOUND`, `ERR_PHASE_NOT_FOUND`, `ERR_BOND_NOT_FOUND`, `ERR_BUILDER_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_CLOSING_NOT_FOUND`, `ERR_LOAN_NOT_FOUND`, `ERR_DRAW_NOT_FOUND`, `ERR_HOA_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`, or `ERR_CONNECTION_NOT_FOUND` (all 404). Because resource URLs are flat, each path carries a single resource identifier, and that identifier is checked before any body reference.
4. **Request shape** — required fields present, types correct, enum values valid, and payload-internal rules such as window ordering and line-item shape; violations yield `ERR_INVALID_REQUEST`, `ERR_INVALID_WINDOW`, or `ERR_INVALID_CONTINGENCY_EXTENSION` (400). A request body that is not a JSON object, and a required string field that is present but empty or all whitespace, each fail here with `ERR_INVALID_REQUEST`.
5. **Optimistic concurrency** — the two OCC checks of §2.7; violations yield `ERR_STALE_PARCEL_VERSION` or `ERR_STALE_AGREEMENT_VERSION` (412).
6. **Target state** — the addressed resource must sit in the transition's required from-state; violations yield the entity's `ERR_<ENTITY>_INVALID_STATE` error (409).
7. **Segregation of duties** — the draw approver must differ from the draw requester; a violation yields `ERR_SEGREGATION_OF_DUTIES` (403).
8. **Temporal rules** — clock and deadline checks such as the contingency deadline and the connection scheduling date; violations yield `ERR_CONTINGENCY_EXPIRED` or `ERR_SCHEDULE_DATE_IN_PAST` (409).
9. **Uniqueness, overlap, and capacity** — builder license uniqueness, provider name uniqueness, the one-open-loan rule, phase window overlap, provider daily capacity, the seated-board minimum, and the HOA control threshold (409).
10. **Cross-entity referential gates** — rules that read the state of a *related* resource: parcel-acquired gates, agreement-active gates, phase readiness, bond-posted gates, parcel/agreement matching, loan selectability, and the behind-schedule precondition (409).
11. **Fiscal gates** — money checks are evaluated last: the draw commitment cap, the bond posting floor, and the bond reduction thresholds (402).

The practical consequence of this ordering is that, for example, a request against a nonexistent parcel surfaces `ERR_PARCEL_NOT_FOUND` before any state rule is consulted, and a stale-version rejection on an extension is reported before the system even considers whether the parcel is still in `CONTINGENCY_ACTIVE`.

### 2.9. Derived Fields, Reconciliation, and Conservation Invariants

Several entities carry derived fields that the server recomputes on every relevant mutation rather than accepting from clients. The parcel's lot counters and absorption metrics recompute on plat recordation, on every closing finalize, on every lot-release cascade, and — for the trailing-window variant — on every clock set. The loan's balance fields recompute on draw funding, draw reversal, and closing finalize. Each such reconciliation independently mutates the parent entity: `updated_at` refreshes and `version` increments by one. The clock-set reconciliation is the lone exception: it mutates the parcel only when a derived value actually changes, so a clock set that moves no derived field leaves the parcel's `updated_at` and `version` untouched.

Two conservation invariants hold at all times and can be used to audit any sequence of operations:

- **Lot inventory conservation.** For every phase, `recorded_lot_count` always equals the sum of that phase's lots across the four sales statuses — `PLATTED` plus `RESERVED` plus `UNDER_CONTRACT` plus `CLOSED`. Lots are created at recordation and never destroyed; they only move between statuses. A reserve followed by an agreement declare-default therefore leaves the phase's `PLATTED` count exactly where it started.
- **Loan balance conservation.** A draw's funding paired with its later reversal leaves `outstanding_balance_cents` and `total_drawn_cents` exactly unchanged; a `REVERSED` draw contributes zero to both aggregates.

## 3. Business Logic & Workflows

### 3.1. Land Acquisition Under Contingency

A `DeveloperOperator` begins the pipeline by creating a development parcel, supplying a `parcel_name`, the `county` the land sits in, and the `earnest_money_cents` deposit — a non-negative integer number of cents. Two planning fields shape later forecasting: `planned_sellout_months`, the number of months over which the developer expects to sell out — a non-negative integer defaulting to 24 when omitted, with zero permitted and simply holding the straight-line pace at zero per §3.8 — and `absorption_method`, which selects which pace variant feeds the projections and takes one of exactly two values, `STRAIGHT_LINE` or `TRAILING_WEIGHTED`, defaulting to `STRAIGHT_LINE`. A new parcel starts in `DRAFT` with all derived counters at zero and its `straight_line_pace_pm` at zero until lots are recorded.

Opening the entitlement contingency moves the parcel from `DRAFT` to `CONTINGENCY_ACTIVE` and fixes the `contingency_end_date` supplied in the request; that deadline must fall strictly after the current logical clock, and a request whose date does not is rejected with `ERR_INVALID_REQUEST`. While the contingency is active the developer may extend it: the extension operation is a self-loop that keeps the parcel in `CONTINGENCY_ACTIVE`, replaces `contingency_end_date` with the supplied `new_contingency_end_date`, and is rejected with `ERR_INVALID_CONTINGENCY_EXTENSION` unless the new date falls strictly later than the deadline currently on record. Because an extension supersedes the deadline other clients may have read, it is one of the two OCC-guarded operations in the system and must carry `expected_parcel_version` as described in §2.7; a parcel whose `version` has moved on rejects the extension with `ERR_STALE_PARCEL_VERSION`.

Clearing the contingency commits the purchase: the parcel moves from `CONTINGENCY_ACTIVE` to `ACQUIRED` and the server stamps `acquisition_close_date` with the current clock (the field is null in every other state). Clearing is only permitted in-period — the current clock must fall on or before `contingency_end_date`, the deadline being inclusive — and a late attempt is rejected with `ERR_CONTINGENCY_EXPIRED`. Alternatively, the developer may walk away in-period by terminating the contingency, moving the parcel to `TERMINATED` with `earnest_money_refunded` set to true, recording that the deposit comes back. Timing matters here: if the clock has already been advanced strictly past the deadline, the parcel will have auto-expired to `TERMINATED` on its own (with `earnest_money_refunded` set to false — the deposit is forfeited on expiry), and the manual termination attempt is then rejected with `ERR_PARCEL_INVALID_STATE` because the parcel no longer sits in `CONTINGENCY_ACTIVE`. The same `ERR_PARCEL_INVALID_STATE` guards every parcel action's from-state: opening the contingency from anything other than `DRAFT`, and clearing, terminating, or extending from anything other than `CONTINGENCY_ACTIVE`. The `earnest_money_refunded` flag is therefore true only on an in-period manual termination and false in every other circumstance, including auto-expiry. `TERMINATED` is terminal; the only way out of `ACQUIRED` is the automatic `SOLD_OUT` transition described in §3.5 and §3.8.

### 3.2. Phasing, Plat Approval, and Lot Recordation

Once a parcel exists, the developer structures it into phases. Creating a phase requires the owning `parcel_id`, a `phase_name`, a `sequence_number` of at least 1 fixing the phase's order within the parcel, a `planned_lot_count` of at least 1, and a planned selling window delimited by `selling_window_start` and `selling_window_end`. The window is a half-open interval: it includes its start and excludes its end, so the end must fall strictly after the start or creation fails with `ERR_INVALID_WINDOW`. Windows of sibling phases — every phase of the same parcel, regardless of status — must not overlap: an overlap exists when the new window's start falls before an existing window's end and that existing window's start falls before the new window's end, and any such overlap is rejected with `ERR_PHASE_WINDOW_OVERLAP`. Pure adjacency is explicitly permitted — a new window starting exactly when a sibling's ends, or ending exactly when a sibling's starts, touches without overlapping. A new phase starts in `PLANNED`.

The plat approval loop is a dialogue between the developer and the county. Submitting a plat moves a phase from `PLANNED` to `PLAT_SUBMITTED` and records the submission's `plat_lot_count` — an integer of at least 1 — and `lot_type` — one of `STANDARD`, `PREMIUM`, or `ESTATE` — while `plat_revision` advances from 0 to 1 on this first submission. A `MunicipalClerk` then reviews the submission by supplying a `decision`. A `decision` of `APPROVE` moves the phase to `PLAT_APPROVED`. A `decision` of `REJECT` moves it to `PLAT_REJECTED` and requires a present, non-empty `rejection_reason` — a rejection without one is rejected itself with `ERR_INVALID_REQUEST` — and the reason is stored on the phase as `plat_rejection_reason`. Rejected plats are resubmitted rather than recreated: submitting again from `PLAT_REJECTED` returns the phase to `PLAT_SUBMITTED`, replaces `plat_lot_count` and `lot_type` with the new submission's values, increments `plat_revision` by one, and clears `plat_rejection_reason` back to null.

Recordation is the act that creates lot inventory. When the clerk records an approved plat, the phase moves from `PLAT_APPROVED` to `PLAT_RECORDED`, `recorded_at` is stamped with the current clock, and the system generates exactly `plat_lot_count` lot rows for the phase: `lot_number` is assigned as the sequence 1 through `plat_lot_count`, each lot's `lot_type` is copied from the recorded plat, and every lot starts with `sales_status` `PLATTED` and `lien_status` `ENCUMBERED`. The phase's `recorded_lot_count` — the count of lot rows belonging to it — is set at this point, and the parcel's derived fields (`total_lots_planned`, `lots_available_count`, the paces, the projection, and the release-eligibility flag of §3.8) recompute, incrementing the parcel's `version`. A lot carries two independent state dimensions throughout its life: `sales_status` walks `PLATTED`, `RESERVED`, `UNDER_CONTRACT`, and terminal `CLOSED`, while `lien_status` walks `ENCUMBERED`, `RELEASE_PENDING`, and terminal `RELEASED`; the two dimensions evolve independently but share the triggers described in §3.5, and a lot's `reserved_agreement_id` is null whenever it sits unreserved in `PLATTED`.

Activation is the phase's gate to selling. A `DeveloperOperator` may move a phase from `PLAT_RECORDED` to `ACTIVE` only when two external conditions hold: the owning parcel's status is `ACQUIRED` (otherwise `ERR_PARCEL_NOT_ACQUIRED`), and an infrastructure bond for this exact phase exists in one of `POSTED`, `PARTIALLY_REDUCED`, or `WORK_ACCEPTED` status (otherwise `ERR_BOND_NOT_POSTED_FOR_PHASE`). An `ACTIVE` phase sells lots until the system observes that `recorded_lot_count` is greater than zero and every lot of the phase has reached `CLOSED`, at which point the phase auto-transitions to terminal `SELLOUT`. Every step of this loop is state-guarded: submitting from anything other than `PLANNED` or `PLAT_REJECTED`, reviewing from anything other than `PLAT_SUBMITTED`, recording from anything other than `PLAT_APPROVED`, or activating from anything other than `PLAT_RECORDED` is rejected with `ERR_PHASE_INVALID_STATE`.

### 3.3. Infrastructure Bonding and Work Acceptance

The county requires the developer to bond phase infrastructure before lots may be released for sale. A `DeveloperOperator` creates the bond record for a phase by supplying the `phase_id` and the `engineer_estimate_cents` — an integer of at least one cent representing the engineer's infrastructure cost estimate. The bond starts `ESTIMATED`, and its `required_bond_cents` is computed provisionally as the engineer's estimate increased by ten percent — the estimate multiplied by 11000 basis points over ten thousand — rounded half-up to whole cents. The `posted_bond_cents` starts at zero and `work_accepted` starts false.

When bids come back, awarding the bid moves the bond from `ESTIMATED` to `BID_FINAL`: the supplied `awarded_bid_cents` — an integer of at least one cent — is recorded and `required_bond_cents` is recomputed on the final basis — ten percent over the awarded bid rather than over the estimate, again rounded half-up to whole cents. For identical phase data the two bases differ, so the required bond changes at award. Posting then moves the bond from `BID_FINAL` to `POSTED`: the supplied `posted_amount_cents` must be at least the current `required_bond_cents` — the boundary is inclusive, an exactly-equal posting succeeds — and anything less is rejected with `ERR_INSUFFICIENT_BOND_POSTED`; the posted amount is stored on `posted_bond_cents`.

As construction progresses and loan exposure falls, the developer may step the bond down. Reducing a `POSTED` bond moves it to `PARTIALLY_REDUCED` and subtracts the supplied `reduction_amount_cents` from `posted_bond_cents`, but only when three conditions all hold; any violation is rejected with `ERR_BOND_REDUCTION_NOT_ELIGIBLE`. First, the parcel's single `ACTIVE` development loan (selected per §3.6; when no such loan exists the gate fails with `ERR_NO_ACTIVE_LOAN`) must carry an `outstanding_balance_cents` of no more than half of `commitment_amount_cents`, the half computed as the commitment times 5000 basis points over ten thousand and the boundary inclusive; this leg is evaluated in exact integer form — twice the outstanding balance must not exceed the commitment — so no rounding arises on it. Second, the reduction must leave the posted amount at no less than half of the current `required_bond_cents`, that half rounded half-up to whole cents and the boundary inclusive. Third, the `reduction_amount_cents` itself must be at least one cent.

Acceptance of the work is the clerk's certification, not the developer's: a `MunicipalClerk` moves a bond from `POSTED` or `PARTIALLY_REDUCED` to `WORK_ACCEPTED`, setting `work_accepted` to true. This split is a deliberate segregation of duties — the clerk certifies acceptance while only the developer may post, reduce, or release. Once the work is accepted, the developer releases the bond, moving it from `WORK_ACCEPTED` to terminal `RELEASED` and zeroing `posted_bond_cents`. Each of these steps requires its from-state — awarding a bid requires `ESTIMATED`, posting requires `BID_FINAL`, reducing requires `POSTED`, accepting work requires `POSTED` or `PARTIALLY_REDUCED`, and releasing requires `WORK_ACCEPTED` — and an attempt from any other state is rejected with `ERR_BOND_INVALID_STATE`.

### 3.4. Builder Takedown Agreements and the Lot Pricing Engine

Before any agreement can be signed, the builder must exist in the system. A `DeveloperOperator` registers each homebuilder with a `builder_name`, a `license_number`, and a `contact_email`; the license number is unique across builders, and a duplicate registration is rejected with `ERR_DUPLICATE_BUILDER_LICENSE`.

A takedown agreement commits a builder to take down a scheduled number of lots at a price that escalates over time. Creating one requires the `parcel_id` whose lots are taken down, the `builder_id` of the counterparty, the `effective_date` that starts both the escalator clock and the default schedule, a `base_lot_price_cents` of at least one cent, an `escalator_rate_bp_per_quarter` of zero or more basis points, a `price_cap_bp` of at least 10000 basis points so the cap can never sit below the base price, a `min_lots_per_quarter` of at least 1 fixing the scheduled commitment per completed quarter, and a `scheduled_lot_count` of at least 1 fixing the total commitment. The agreement starts in `DRAFT` with `closed_lot_count` at zero. Activating it moves it from `DRAFT` to `ACTIVE` and requires the parcel to be `ACQUIRED`, failing otherwise with `ERR_PARCEL_NOT_ACQUIRED`.

Pricing terms may be amended while the agreement is `ACTIVE` — the amendment is a self-loop that keeps the agreement `ACTIVE`. Either a `DeveloperOperator` or the `BuilderRep` whose builder owns the agreement may amend; any of `base_lot_price_cents`, `escalator_rate_bp_per_quarter`, `price_cap_bp`, and `min_lots_per_quarter` that are provided replace the stored values, and the rest are left untouched. Provided values must satisfy the same per-field minima as at creation, and an out-of-range value fails shape validation with `ERR_INVALID_REQUEST`. Because an amendment supersedes pricing terms other parties may have priced against, the request must carry `expected_agreement_version` per §2.7 and is rejected with `ERR_STALE_AGREEMENT_VERSION` when the agreement has moved on.

The lot pricing engine runs at closing-creation time and freezes its result onto the closing. It proceeds in precise steps. First, it counts the quarters elapsed since the agreement's `effective_date` at the current logical clock: whole elapsed months are twelve times the difference in calendar years plus the difference in calendar months, reduced by one when the clock's day-of-month falls earlier than the effective date's day-of-month; elapsed quarters are that whole-month count divided by three and rounded down, never below zero. Second, the escalated price is the `base_lot_price_cents` multiplied by one plus the quarterly escalator rate (the basis-point rate over ten thousand), that factor raised to the power of the elapsed-quarters count — the escalator compounds quarterly. Third, the cap is the base price multiplied by `price_cap_bp` over ten thousand, and the escalated figure is taken at the lesser of itself and the cap. Fourth, a volume discount is selected from the agreement's `closed_lot_count` at that moment: ten or more closed lots earns a 500-basis-point discount, five through nine closed lots earns 250 basis points, and four or fewer earns none. Fifth, the capped price is reduced by the selected discount fraction, and the result is rounded half-up to whole cents — this is the only rounding step in the entire calculation — and frozen as the closing's `contract_price_cents`.

An agreement completes itself: when a finalize cascade (§3.5) carries `closed_lot_count` to `scheduled_lot_count` — the equality boundary triggers, so reaching exactly the scheduled count completes the agreement — an `ACTIVE` agreement auto-transitions to terminal `COMPLETED`. The default-and-cure cycle and termination are covered in §3.7.

### 3.5. Lot Reservations, Closings, and Lien Release

Lots enter the market through reservation. A `BuilderRep` reserves a lot by supplying the `agreement_id` of an agreement their builder owns; the check chain requires the agreement to be `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE` otherwise), the lot's phase to be `ACTIVE` (`ERR_PHASE_INVALID_STATE` otherwise), the agreement's parcel to be the same parcel the lot's phase belongs to (`ERR_AGREEMENT_PARCEL_MISMATCH` otherwise), and the lot's `sales_status` to be `PLATTED` (`ERR_LOT_INVALID_STATE` otherwise). The chain fires in §2.8 order: the lot's own state gate (priority 6) is evaluated first, and the agreement-active, phase-active, and parcel-match gates follow as priority-10 referential checks in the order listed. A successful reservation moves the lot from `PLATTED` to `RESERVED`, records the holding agreement on `reserved_agreement_id`, decrements the parcel's `lots_available_count` by one, and increments both the lot's `version` and the parcel's `version`.

A closing is opened on a reserved lot by the same builder's representative, supplying the `lot_id` and the `agreement_id`. The lot must currently be `RESERVED` under exactly that agreement — a lot whose `reserved_agreement_id` names any other agreement, or that is not reserved at all, is rejected with `ERR_LOT_NOT_RESERVED_BY_AGREEMENT` — and the agreement must still be `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE` otherwise). Creation also anchors the closing to the parcel's development loan: the candidate set is the parcel's loans in `ACTIVE` status, at most one of which can exist (§3.6 explains the uniqueness rule), and an empty set is rejected with `ERR_NO_ACTIVE_LOAN`; the selected loan's `id` is recorded on the closing's `loan_id`. At creation the pricing engine of §3.4 computes and freezes `contract_price_cents`, and the lien release price is computed and frozen as `release_price_cents`: the contract price multiplied by the selected loan's `release_price_floor_bp` over ten thousand, rounded half-up to whole cents. The closing starts `PENDING` with `payment_applied_cents` at zero and `finalized_at` null, and its creation advances the lot on both dimensions at once — `sales_status` from `RESERVED` to `UNDER_CONTRACT` and `lien_status` from `ENCUMBERED` to `RELEASE_PENDING`.

Finalization is the lender's act. A `LenderOfficer` finalizes a `PENDING` closing, moving it to terminal `CLOSED` and firing a seven-link cascade:

1. The lot's `sales_status` moves from `UNDER_CONTRACT` to `CLOSED` and its `lien_status` from `RELEASE_PENDING` to `RELEASED` — the lender releases the lot from the loan lien — and `finalized_at` is stamped with the current clock.
2. The agreement's `closed_lot_count` increments by one; if the increment carries it to at least `scheduled_lot_count`, the agreement auto-transitions from `ACTIVE` to `COMPLETED`.
3. The release payment lands on the loan: `payment_applied_cents` is set to the lesser of the closing's frozen `release_price_cents` and the loan's current `outstanding_balance_cents` — the clamp guarantees the balance can never go negative — then the loan's `outstanding_balance_cents` decreases by that payment, its `total_release_paid_cents` increases by the same amount, and the loan's `version` increments.
4. If the balance change leaves `outstanding_balance_cents` at exactly zero while `total_drawn_cents` is greater than zero, the loan auto-transitions from `ACTIVE` to terminal `PAID_OFF`.
5. The parcel's derived fields recompute — `lots_closed_count`, `lots_available_count`, `closed_pct`, the paces, `projected_months_to_sellout`, and `next_phase_release_eligible` — and the parcel's `version` increments.
6. Following the lot's closure upward: if every lot of the closing's phase is now `CLOSED` the phase auto-transitions from `ACTIVE` to `SELLOUT`, and if every recorded lot of the parcel is now `CLOSED` with `total_lots_planned` greater than zero the parcel auto-transitions from `ACQUIRED` to terminal `SOLD_OUT`.
7. Following the closed ratio sideways: each homeowners association of this parcel sitting in `DECLARANT_CONTROL` whose ratio-path threshold of §3.8 is now satisfied auto-transitions to `TRANSITIONING`; the statutory path never fires from this cascade.

The closing's own `version` increments as well. Alternatively, a `PENDING` closing may be cancelled — by the `BuilderRep` whose builder owns the agreement, or by a `DeveloperOperator` — moving it to terminal `CANCELLED` and reverting the lot: `sales_status` returns from `UNDER_CONTRACT` to `RESERVED` (the reservation stands) and `lien_status` returns from `RELEASE_PENDING` to `ENCUMBERED`. Finalizing or cancelling a closing that is no longer `PENDING` is rejected with `ERR_CLOSING_INVALID_STATE`.

### 3.6. The Development Loan and Draw Pipeline

The development loan finances the work between acquisition and sellout. A `DeveloperOperator` creates a loan with the securing `parcel_id`, a `commitment_amount_cents` of at least one cent, and a `release_price_floor_bp` — the lot lien-release price expressed as basis points of the contract price, between 1 and 10000 inclusive. Only one open loan may exist per parcel: creating a second loan while one sits in `DRAFT` or `ACTIVE` is rejected with `ERR_LOAN_ALREADY_EXISTS`, though a `PAID_OFF` loan does not block a successor. A new loan starts in `DRAFT` with `outstanding_balance_cents`, `total_drawn_cents`, and `total_release_paid_cents` all at zero, and activating it — permitted only once the parcel is `ACQUIRED`, failing with `ERR_PARCEL_NOT_ACQUIRED` otherwise — moves it to `ACTIVE`; activating a loan that is not `DRAFT` is rejected with `ERR_LOAN_INVALID_STATE`.

Three derived quantities track the loan's life. `outstanding_balance_cents` is the sum of `net_disbursed_cents` over draws currently `FUNDED` minus the sum of `payment_applied_cents` over closings `CLOSED` against this loan; the finalize clamp keeps it from ever going negative. `total_drawn_cents` accumulates the `net_disbursed_cents` of currently-`FUNDED` draws, and `total_release_paid_cents` accumulates the payments applied by `CLOSED` closings. By the conservation invariant of §2.9, funding a draw and later reversing it leaves both balance figures exactly as they were.

Draws fund the work. A `DeveloperOperator` requests a draw against a loan by supplying the `loan_id` and a `line_items` array; the loan must be `ACTIVE` (`ERR_LOAN_NOT_ACTIVE` otherwise). Each line item carries a `description` and an integer `amount_cents` of at least one cent, and the array must contain at least one item — malformed payloads fail with `ERR_INVALID_REQUEST`. The requester's `X-User-ID` is stamped onto `requested_by_user_id`, anchoring segregation of duties. Creation is also subject to the commitment cap: the cumulative gross of the loan's draws in `REQUESTED`, `APPROVED`, or `FUNDED` status plus the new draw's gross must not exceed `commitment_amount_cents`, and a breach is rejected with `ERR_DRAW_EXCEEDS_COMMITMENT`.

The disbursement arithmetic is frozen onto the draw at creation in a pinned rounding order. The `gross_amount_cents` is the plain sum of the line items' amounts — integer cents, no rounding at this step. The `retainage_cents` is five percent of the gross — the gross times 500 basis points over ten thousand — rounded half-up to whole cents; this is the first rounding step. The `draw_fee_cents` is one-half percent of the post-retainage base — the gross minus the retainage, times 50 basis points over ten thousand — rounded half-up to whole cents; this is the second rounding step, computed on the post-retainage base, not on the gross. The `net_disbursed_cents` is the gross minus the retainage minus the fee. The order is load-bearing: a gross of 1,000,100 cents yields retainage of 50,005 cents, a fee of 4,750 cents on the remaining 950,095, and a net of 945,345 cents, whereas computing the fee first and the retainage second would yield 945,344 cents and is incorrect.

A `LenderOfficer` then disposes of the request. Approving moves the draw from `REQUESTED` to `APPROVED` and records the approver's `X-User-ID` on `approved_by_user_id`, but the approver must not be the requester — an approval whose `X-User-ID` equals the draw's `requested_by_user_id` is rejected with `ERR_SEGREGATION_OF_DUTIES`. Rejecting moves it from `REQUESTED` to terminal `REJECTED` and accepts an optional `reason`. Funding an `APPROVED` draw requires the loan still to be `ACTIVE` (`ERR_LOAN_NOT_ACTIVE` otherwise), moves the draw to `FUNDED`, and adds `net_disbursed_cents` to both the loan's `outstanding_balance_cents` and its `total_drawn_cents`, incrementing both resources' versions. Reversing a `FUNDED` draw moves it to terminal `REVERSED` and subtracts the same `net_disbursed_cents` from both loan aggregates — the compensating action that preserves the balance-conservation invariant. Each disposal step is state-guarded: approving or rejecting requires `REQUESTED`, funding requires `APPROVED`, and reversing requires `FUNDED`, with any other from-state rejected as `ERR_DRAW_INVALID_STATE`.

### 3.7. Agreement Default, Cure, and the Lot-Release Cascade

A builder who falls behind the takedown schedule can be placed in default. The schedule check runs against completed quarters: declaring default on an `ACTIVE` agreement requires the agreement's `closed_lot_count` to be strictly less than the elapsed quarters since `effective_date` (computed exactly as in §3.4) multiplied by `min_lots_per_quarter`; a builder who has closed at least the scheduled number is not behind, and the attempt is rejected with `ERR_AGREEMENT_NOT_BEHIND_SCHEDULE`. A successful declaration moves the agreement to `DEFAULTED`, records the supplied `reason` — a required, non-empty string — on `default_reason`, and fires the four-link lot-release cascade:

1. Every `PENDING` closing whose lot is reserved under this agreement is cancelled to `CANCELLED`.
2. Each such cancellation reverts its lot on both dimensions: `lien_status` from `RELEASE_PENDING` back to `ENCUMBERED` and `sales_status` from `UNDER_CONTRACT` back to `RESERVED` — so a lot that was mid-closing hops through `RESERVED` on its way out.
3. Every lot whose `reserved_agreement_id` names this agreement and whose `sales_status` now reads `RESERVED` — including both lots that were merely reserved and lots that just hopped back from `UNDER_CONTRACT` — is released to `PLATTED` with `reserved_agreement_id` cleared to null.
4. The parcel's derived fields recompute (`lots_available_count` rises as lots return, and `closed_pct`, the paces, `projected_months_to_sellout`, and `next_phase_release_eligible` follow), and the parcel's `version` increments, as does the agreement's.

A default need not be fatal. Curing a `DEFAULTED` agreement returns it to `ACTIVE` and clears `default_reason` to null; the request carries a `cure_note` for the record. The cycle deliberately does not restore the released lots: reservations that were torn down stay torn down, and the builder must reserve anew under the cured agreement. Termination is the hard exit — from either `ACTIVE` or `DEFAULTED` the developer may terminate the agreement into terminal `TERMINATED`, firing the same four-link lot-release cascade as a default declaration. All agreement actions are state-guarded: activation requires `DRAFT`, amendment requires `ACTIVE`, default declaration requires `ACTIVE`, curing requires `DEFAULTED`, and termination requires `ACTIVE` or `DEFAULTED` — any attempt from the wrong state is rejected with `ERR_AGREEMENT_INVALID_STATE`.

### 3.8. Absorption Forecasting, Sellout, and the HOA Control Transfer

The parcel carries a small forecasting engine in its derived fields, all recomputed on plat recordation, on every closing finalize, on every lot-release cascade, and — for the trailing windows — on every clock set. `total_lots_planned` is the count of recorded lots across all of the parcel's phases; lots exist only after recordation, so plats that are merely approved contribute nothing yet. `lots_closed_count` counts the parcel's lots whose `sales_status` is `CLOSED`, and `lots_available_count` those in `PLATTED`. The `closed_pct` is one hundred times the closed count divided by the total, rounded half-up to two decimal places, and reads zero while no lots are recorded.

Two pace variants compete to feed the projection. The `straight_line_pace_pm` is the `total_lots_planned` divided by `planned_sellout_months`, rounded half-up to four decimal places, and reads zero when `planned_sellout_months` is zero; it derives from plan and ignores actual closings. The `trailing_weighted_pace_pm` derives from actuals: count the parcel's `CLOSED` closings whose `finalized_at` falls in the trailing thirty-day window ending at the current clock — both endpoints included — and call it C1; count those in the window from sixty to thirty days back, including the sixty-day end but excluding the thirty-day end, as C2; and those from ninety to sixty days back on the same half-open basis as C3. A closing exactly thirty days back therefore belongs to C1 and is never double-counted. The pace is one-half of C1 plus three-tenths of C2 plus one-fifth of C3, rounded half-up to four decimal places. The `selected_pace_pm` is the straight-line figure when the parcel's `absorption_method` is `STRAIGHT_LINE` and the trailing-weighted figure when it is `TRAILING_WEIGHTED`; for identical parcel data the two paces diverge whenever actual closings diverge from plan.

From the selected pace, `projected_months_to_sellout` is the remaining lot count — `total_lots_planned` minus `lots_closed_count` — divided by the selected pace, rounded half-up to one decimal place; when the selected pace is zero the projection is null. The `next_phase_release_eligible` flag reads true exactly when the projection is not null and is at most six months — the lead time the pipeline assumes for bringing the next phase to market.

Sellout is the pipeline's destination. A phase auto-completes to `SELLOUT` when every one of its recorded lots has closed, and the parcel auto-completes from `ACQUIRED` to `SOLD_OUT` when `total_lots_planned` is greater than zero and every recorded lot of the parcel has closed; both transitions fire out of the closing finalize cascade of §3.5.

The homeowners association tracks the same closing flow. A `DeveloperOperator` creates the association record with the governed `parcel_id`, an `hoa_name`, a `statutory_control_end` — the statutory sunset after which control may transfer regardless of sales — and an optional `control_transfer_pct_bp`, any non-negative integer of basis points, defaulting to 7500 basis points, meaning declarant control ends once three-quarters of the lots have closed. The record starts `FORMATION_PENDING`, and forming the association moves it to `DECLARANT_CONTROL`, which requires the parcel to be `ACQUIRED` (`ERR_PARCEL_NOT_ACQUIRED` otherwise).

Control transfers through two paths, evaluated with different boundary semantics. The ratio path uses integer cross-multiplication without floating point: transfer is due when `lots_closed_count` times ten thousand is greater than or equal to `total_lots_planned` times `control_transfer_pct_bp` — the boundary is inclusive, so a parcel sitting exactly on the threshold transfers; the ratio path also requires `total_lots_planned` greater than zero, since zero lots can never satisfy it. The statutory path is due when the current clock falls strictly later than `statutory_control_end` — the boundary is exclusive, so the clock reading exactly the sunset date does not transfer. Either path suffices. Evaluating control — which a `DeveloperOperator`, or the `HOAManager` of that association, may invoke — moves the association from `DECLARANT_CONTROL` to `TRANSITIONING` when either condition holds and is rejected with `ERR_CONTROL_THRESHOLD_NOT_MET` when neither does. The same threshold also fires automatically: any closing finalize that carries the ratio to the threshold auto-transitions every `DECLARANT_CONTROL` association of the parcel to `TRANSITIONING` as the seventh link of the finalize cascade. Only the ratio path fires automatically — the statutory path transfers control solely through an explicit evaluate-control call, and setting the clock past `statutory_control_end` does not by itself move any association.

Completing the transition belongs to the association's own `HOAManager`. Supplying a `seated_board_count` of at least three seated homeowner board members moves the association from `TRANSITIONING` to terminal `HOMEOWNER_CONTROL` and records the count on `board_seated_count` (which is null until that moment); a request naming fewer than three is rejected with `ERR_BOARD_NOT_SEATED`. Attempts to drive any HOA transition from the wrong state surface `ERR_HOA_INVALID_STATE`.

### 3.9. Utility Providers, Impact Fees, and Connection Scheduling

Utility capacity is administered by the county. A `MunicipalClerk` registers each provider or district with a `provider_name` — unique across providers, duplicates rejected with `ERR_DUPLICATE_PROVIDER_NAME` — a `utility_type` of `WATER`, `SEWER`, or `ELECTRIC`, and a `max_connections_per_day` of at least 1 bounding the provider's daily scheduling capacity.

A `DeveloperOperator` requests a connection for a lot by supplying the `lot_id`, the `provider_id`, and the requested `scheduled_date`, which is capacity-counted by calendar day. The lot's phase must be `ACTIVE` — lots in earlier phases are not ready for connections, and the request is rejected with `ERR_PHASE_NOT_READY_FOR_CONNECTIONS`. At creation the impact fee is computed and frozen onto `impact_fee_cents`. The fee indexes a type-specific base by whole years elapsed since the ordinance epoch of 2024-01-01: the elapsed time in days between that epoch and the current clock's date, divided by 365 and rounded down, clamped at zero, gives the year count. The base fees are 250,000 cents for `WATER`, 300,000 cents for `SEWER`, and 175,000 cents for `ELECTRIC`, and the fee is the base multiplied by one plus 300 basis points over ten thousand, that factor raised to the year count — a three-percent annual indexation, compounded — with the result rounded half-up to whole cents as the only rounding step. At the startup clock of 2026-08-01 the year count is two, so a water connection's fee computes to 265,225 cents. The connection starts in `REQUESTED`.

Scheduling belongs to the clerk and enforces two rules. Moving a connection from `REQUESTED` to `SCHEDULED` first requires the `scheduled_date`'s calendar day not to fall before the current clock's calendar day — a same-day schedule is fine, a past day fails with `ERR_SCHEDULE_DATE_IN_PAST`. Second, the provider must have capacity left on that day: count the provider's connections on the same calendar day in `SCHEDULED` or `CONNECTED` status, and when that count has already reached `max_connections_per_day` the schedule is rejected with `ERR_PROVIDER_CAPACITY_EXCEEDED`. The boundary is exact: when the count sits one below the maximum the schedule succeeds and the day becomes full. Scheduling consumes one slot of the provider's daily capacity. A scheduled connection is marked `CONNECTED` by the clerk when the work is done. The developer may cancel from either `REQUESTED` or `SCHEDULED` into terminal `CANCELLED`; cancelling a scheduled connection frees the provider's daily slot for that day. Wrong-state attempts on any of these transitions surface `ERR_CONNECTION_INVALID_STATE`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that act on an existing resource — including all state-transition actions — return `200 OK`. The table below summarizes the HTTP contract only; the request parameters, preconditions, and side effects of each operation are specified in the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/parcels` | Create a development parcel (starts `DRAFT`) | DeveloperOperator |
| GET | `/api/parcels` | List parcels, paginated, filterable by status | Any |
| GET | `/api/parcels/{id}` | Get one parcel with derived fields | Any |
| POST | `/api/parcels/{id}/open-contingency` | Open the entitlement contingency (`DRAFT` to `CONTINGENCY_ACTIVE`) | DeveloperOperator |
| POST | `/api/parcels/{id}/extend-contingency` | Extend the contingency deadline (self-loop, OCC-guarded) | DeveloperOperator |
| POST | `/api/parcels/{id}/clear-contingency` | Clear the contingency and acquire the parcel | DeveloperOperator |
| POST | `/api/parcels/{id}/terminate-contingency` | Terminate in-period with deposit refund | DeveloperOperator |
| POST | `/api/phases` | Create a phase (`PLANNED`); window validations apply | DeveloperOperator |
| GET | `/api/phases` | List phases, filterable by parcel and status | Any |
| GET | `/api/phases/{id}` | Get one phase | Any |
| POST | `/api/phases/{id}/submit-plat` | Submit or resubmit a plat for review | DeveloperOperator |
| POST | `/api/phases/{id}/review-plat` | Approve or reject a submitted plat | MunicipalClerk |
| POST | `/api/phases/{id}/record-plat` | Record an approved plat; generates the phase's lots | MunicipalClerk |
| POST | `/api/phases/{id}/activate` | Activate a recorded phase for selling | DeveloperOperator |
| POST | `/api/infrastructure-bonds` | Create a bond record for a phase (`ESTIMATED`) | DeveloperOperator |
| GET | `/api/infrastructure-bonds` | List bonds, filterable by phase and status | Any |
| GET | `/api/infrastructure-bonds/{id}` | Get one bond | Any |
| POST | `/api/infrastructure-bonds/{id}/award-bid` | Award the infrastructure bid; required bond switches to the final basis | DeveloperOperator |
| POST | `/api/infrastructure-bonds/{id}/post-bond` | Post the bond (must cover the requirement, inclusive) | DeveloperOperator |
| POST | `/api/infrastructure-bonds/{id}/reduce` | Step down a posted bond under the reduction thresholds | DeveloperOperator |
| POST | `/api/infrastructure-bonds/{id}/accept-work` | Clerk certification of infrastructure acceptance | MunicipalClerk |
| POST | `/api/infrastructure-bonds/{id}/release` | Release an accepted bond; posted amount zeroed | DeveloperOperator |
| POST | `/api/builders` | Register a homebuilder (license number unique) | DeveloperOperator |
| GET | `/api/builders` | List builders, paginated | Any |
| GET | `/api/builders/{id}` | Get one builder | Any |
| POST | `/api/takedown-agreements` | Create a builder takedown agreement (`DRAFT`) | DeveloperOperator |
| GET | `/api/takedown-agreements` | List agreements, filterable by parcel, builder, and status | Any |
| GET | `/api/takedown-agreements/{id}` | Get one agreement | Any |
| POST | `/api/takedown-agreements/{id}/activate` | Activate an agreement (requires parcel `ACQUIRED`) | DeveloperOperator |
| POST | `/api/takedown-agreements/{id}/amend` | Amend pricing terms in place (self-loop, OCC-guarded) | DeveloperOperator, BuilderRep (own agreement) |
| POST | `/api/takedown-agreements/{id}/declare-default` | Declare a behind-schedule builder in default; releases reserved lots | DeveloperOperator |
| POST | `/api/takedown-agreements/{id}/cure` | Cure a default back to `ACTIVE`; released lots stay released | DeveloperOperator |
| POST | `/api/takedown-agreements/{id}/terminate` | Terminate an agreement; releases reserved lots | DeveloperOperator |
| GET | `/api/lots` | List lots, filterable by phase, statuses, and reserving agreement | Any |
| GET | `/api/lots/{id}` | Get one lot | Any |
| POST | `/api/lots/{id}/reserve` | Reserve a platted lot under an active agreement of the caller's builder | BuilderRep (own agreement) |
| POST | `/api/lot-closings` | Open a closing on a reserved lot; freezes contract and release prices | BuilderRep (own agreement) |
| GET | `/api/lot-closings` | List closings, filterable by lot, agreement, loan, and status | Any |
| GET | `/api/lot-closings/{id}` | Get one closing | Any |
| POST | `/api/lot-closings/{id}/finalize` | Finalize a closing: lender confirms funds and releases the lot from the lien | LenderOfficer |
| POST | `/api/lot-closings/{id}/cancel` | Cancel a pending closing; the reservation stands | BuilderRep (own agreement), DeveloperOperator |
| POST | `/api/development-loans` | Create a development loan (`DRAFT`); one open loan per parcel | DeveloperOperator |
| GET | `/api/development-loans` | List loans, filterable by parcel and status | Any |
| GET | `/api/development-loans/{id}` | Get one loan | Any |
| POST | `/api/development-loans/{id}/activate` | Activate a loan (requires parcel `ACQUIRED`) | DeveloperOperator |
| POST | `/api/loan-draws` | Request a draw; disbursement arithmetic computed and frozen | DeveloperOperator |
| GET | `/api/loan-draws` | List draws, filterable by loan and status | Any |
| GET | `/api/loan-draws/{id}` | Get one draw | Any |
| POST | `/api/loan-draws/{id}/approve` | Approve a draw; approver must differ from requester | LenderOfficer |
| POST | `/api/loan-draws/{id}/reject` | Reject a draw | LenderOfficer |
| POST | `/api/loan-draws/{id}/fund` | Fund an approved draw onto the loan balance | LenderOfficer |
| POST | `/api/loan-draws/{id}/reverse` | Reverse a funded draw (compensating action) | LenderOfficer |
| POST | `/api/hoa-associations` | Create the parcel's HOA record (`FORMATION_PENDING`) | DeveloperOperator |
| GET | `/api/hoa-associations` | List associations, filterable by parcel and status | Any |
| GET | `/api/hoa-associations/{id}` | Get one association | Any |
| POST | `/api/hoa-associations/{id}/form` | Form the association into declarant control | DeveloperOperator |
| POST | `/api/hoa-associations/{id}/evaluate-control` | Evaluate the control-transfer threshold | DeveloperOperator, HOAManager (own association) |
| POST | `/api/hoa-associations/{id}/complete-transition` | Complete the transition once a homeowner board is seated | HOAManager (own association) |
| POST | `/api/utility-providers` | Register a utility provider with daily connection capacity | MunicipalClerk |
| GET | `/api/utility-providers` | List providers, filterable by utility type | Any |
| GET | `/api/utility-providers/{id}` | Get one provider | Any |
| POST | `/api/utility-connections` | Request a connection for a lot; impact fee computed and frozen | DeveloperOperator |
| GET | `/api/utility-connections` | List connections, filterable by lot, provider, and status | Any |
| GET | `/api/utility-connections/{id}` | Get one connection | Any |
| POST | `/api/utility-connections/{id}/schedule` | Schedule a connection; enforces past-date and daily-capacity rules | MunicipalClerk |
| POST | `/api/utility-connections/{id}/mark-connected` | Mark a scheduled connection as connected | MunicipalClerk |
| POST | `/api/utility-connections/{id}/cancel` | Cancel a requested or scheduled connection; frees the capacity slot | DeveloperOperator |
| POST | `/api/_clock/set_current_utc` | Set the server's logical clock (test-driving capability) | DeveloperOperator |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this catalogue fixes only the identifier-to-status mapping. One fallback sits outside the catalogue: a request matching no route, or naming an unsupported method on a matched route, surfaces `ERR_NOT_FOUND` (404).

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_WINDOW` | 400 |
| `ERR_INVALID_CONTINGENCY_EXTENSION` | 400 |
| `ERR_PARCEL_NOT_FOUND` | 404 |
| `ERR_PHASE_NOT_FOUND` | 404 |
| `ERR_BOND_NOT_FOUND` | 404 |
| `ERR_BUILDER_NOT_FOUND` | 404 |
| `ERR_AGREEMENT_NOT_FOUND` | 404 |
| `ERR_LOT_NOT_FOUND` | 404 |
| `ERR_CLOSING_NOT_FOUND` | 404 |
| `ERR_LOAN_NOT_FOUND` | 404 |
| `ERR_DRAW_NOT_FOUND` | 404 |
| `ERR_HOA_NOT_FOUND` | 404 |
| `ERR_PROVIDER_NOT_FOUND` | 404 |
| `ERR_CONNECTION_NOT_FOUND` | 404 |
| `ERR_STALE_PARCEL_VERSION` | 412 |
| `ERR_STALE_AGREEMENT_VERSION` | 412 |
| `ERR_PARCEL_INVALID_STATE` | 409 |
| `ERR_PHASE_INVALID_STATE` | 409 |
| `ERR_BOND_INVALID_STATE` | 409 |
| `ERR_AGREEMENT_INVALID_STATE` | 409 |
| `ERR_LOT_INVALID_STATE` | 409 |
| `ERR_CLOSING_INVALID_STATE` | 409 |
| `ERR_LOAN_INVALID_STATE` | 409 |
| `ERR_DRAW_INVALID_STATE` | 409 |
| `ERR_HOA_INVALID_STATE` | 409 |
| `ERR_CONNECTION_INVALID_STATE` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_CONTINGENCY_EXPIRED` | 409 |
| `ERR_SCHEDULE_DATE_IN_PAST` | 409 |
| `ERR_DUPLICATE_BUILDER_LICENSE` | 409 |
| `ERR_DUPLICATE_PROVIDER_NAME` | 409 |
| `ERR_LOAN_ALREADY_EXISTS` | 409 |
| `ERR_PHASE_WINDOW_OVERLAP` | 409 |
| `ERR_PROVIDER_CAPACITY_EXCEEDED` | 409 |
| `ERR_BOARD_NOT_SEATED` | 409 |
| `ERR_CONTROL_THRESHOLD_NOT_MET` | 409 |
| `ERR_PARCEL_NOT_ACQUIRED` | 409 |
| `ERR_AGREEMENT_NOT_ACTIVE` | 409 |
| `ERR_PHASE_NOT_READY_FOR_CONNECTIONS` | 409 |
| `ERR_BOND_NOT_POSTED_FOR_PHASE` | 409 |
| `ERR_AGREEMENT_PARCEL_MISMATCH` | 409 |
| `ERR_LOT_NOT_RESERVED_BY_AGREEMENT` | 409 |
| `ERR_NO_ACTIVE_LOAN` | 409 |
| `ERR_LOAN_NOT_ACTIVE` | 409 |
| `ERR_AGREEMENT_NOT_BEHIND_SCHEDULE` | 409 |
| `ERR_DRAW_EXCEEDS_COMMITMENT` | 402 |
| `ERR_INSUFFICIENT_BOND_POSTED` | 402 |
| `ERR_BOND_REDUCTION_NOT_ELIGIBLE` | 402 |
