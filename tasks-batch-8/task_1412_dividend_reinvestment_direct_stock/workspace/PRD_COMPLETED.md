# DRIP Administration API — Product Requirements Document

## 1. Introduction

Issuers that sponsor dividend reinvestment and direct stock purchase plans delegate a demanding book-of-record operation to their plan administrator. Investors enroll in the plan, elect how much of each dividend to reinvest, buy additional shares through optional cash purchase windows, and eventually transfer, gift, or terminate their positions. Every one of those events moves money and fractional shares, consumes or creates tax lots, and may trigger fees — and every one is audit-sensitive. A rounding slip in a discounted reinvestment price, a purchase window that overlaps a dividend blackout, or a fee that should have been waived becomes a reconciliation problem measured in real dollars and regulatory exposure.

This document specifies the DRIP Administration API, the system an issuer's plan administrator uses to run that operation end to end. The API is mounted under `/drip` and serves two actor roles: the administrator operating the plan and the participating investor acting on their own account. It governs plan configuration and lifecycle, participant registration, enrollment and participation elections, dividend declaration through settlement, optional cash purchase windows and orders, fee assessment and waiver, plan communications, share transfers and gifts, termination settlement, and per-year tax reporting. All temporal reasoning in the system is driven by a server-maintained logical clock rather than wall-clock time, and all monetary and share arithmetic follows a single deterministic rounding discipline, so that two independent readers of this document arrive at the same numbers.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contracts, cross-cutting principles, and invariants that apply to every endpoint and every entity in the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The system recognizes exactly two roles, spelled `PlanAdmin` and `Participant`. A request with missing headers, or whose declared role is not one of these two, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted on the target endpoint — or a `Participant`-role request that touches a resource owned by a different participant — is rejected with `ERR_FORBIDDEN` (HTTP 403).

The meaning of `X-User-ID` differs by role. When `X-User-Role` is `PlanAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`. When `X-User-Role` is `Participant`, `X-User-ID` is the `id` of the acting `Participant`, and ownership checks on any resource that traces back to a participant compare the resource's owning participant reference to `X-User-ID`: an enrollment is owned through its `participant_id`, a purchase order through the `enrollment_id` it was placed under, a transfer instruction through its `source_enrollment_id`, and ledger entries, tax lots, fee assessments, and tax reports through the enrollment they belong to. A `Participant` reading their own participant record may only address their own `id`; all other participant-scoped reads likewise return only the caller's own resources.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items from the start of the result set and defaults to 0; it must be non-negative. A non-integer `limit` or `offset`, a `limit` outside 1–100, or a negative `offset` is rejected with `ERR_VALIDATION` (HTTP 400), as is a filter query parameter whose value is not a member of the filtered enum. Unless otherwise specified, every list endpoint returns resources sorted by creation timestamp in ascending order, with ties on the timestamp — common while the logical clock stands still — broken by insertion order. List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope; `total_count` is the size of the full filtered result set before pagination, and `has_more` is true exactly when `offset + limit` is less than `total_count`.

### 2.4. The Logical Clock

The system never consults wall-clock time for any business decision or persisted timestamp. Every temporal decision — record-date eligibility, window opening and closing, dividend blackout computation, notice lead time, dividend payable gating, and window schedule sanity — is evaluated against a server-maintained logical clock, and every timestamp the system stamps onto a stored record — `created_at`, `updated_at`, `acquired_at`, `published_at`, `executed_at`, and `terminated_at` — is read from that clock; the envelope's `api_request_timestamp` is the sole wall-clock reading in a response and carries no business meaning. At server startup the logical clock reads exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock time thereafter. A `PlanAdmin`-only test-driving capability sets the logical clock to a supplied `to_iso8601` instant — no monotonicity check is applied, so the clock can be moved in either direction — and the response reports the new value as `current_utc`. Workflow narratives throughout §3 phrase temporal preconditions in terms of this logical clock.

### 2.5. Money, Share Quantities, and Rounding Discipline

All monetary values are integer cents, carried in fields whose names end in `_cents`; comparisons of monetary limits are exact integer comparisons. All share quantities are decimal numbers with exactly four decimal places, rounded half-up. Whenever a monetary intermediate must be rounded, it is rounded half-up to whole cents. Fractional configuration and election values — `discount_pct`, `ocp_fee_pct`, and `reinvest_pct` — are expressed as decimal fractions, so 0.05 means five percent.

Three rounding orders are pinned and must not be reordered. First, a discounted reinvestment price is rounded half-up to whole cents before any share division takes place. Second, when a dividend is split between reinvestment and cash under a partial election, the reinvested portion is rounded half-up to whole cents first and the cash payout is the remainder. Third, in a fractional-share sale the gross proceeds are rounded half-up to whole cents first and the fee is subtracted only after that rounding. The full formulas live in §3; this section fixes the order of operations they depend on.

### 2.6. Common Resource Properties

Every primary resource carries a standard set of system-managed fields: `id`, a server-minted UUID with no type prefix; `created_at`, an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created; `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation; and `version`, an integer that starts at 1 on creation and increments by exactly 1 on every mutation of the resource, including mutations produced by system cascades. One entity is exempt: a share ledger entry is an immutable record and carries only `id` and `created_at` — both `updated_at` and `version` are absent on ledger entries. Recomputing a derived figure — an enrollment's `share_balance` and `total_cost_basis_cents` (§2.9) or a window's `submitted_total_cents` (§3.5) — is not a mutation of the owning resource: it neither refreshes `updated_at` nor increments `version`.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and no other endpoint takes a version field.

A `PATCH /drip/plans/{id}` request must carry `expected_plan_version`, holding the value of the plan's `version` the client last observed. If the plan's current `version` no longer matches — because an intervening mutation has advanced it — the modification is rejected with `ERR_STALE_PLAN_VERSION` (HTTP 412), since the client's edits were computed against a stale configuration of discounts, limits, and fees and applying them would silently overwrite the intervening modification.

A `PATCH /drip/enrollments/{id}/election` request must carry `expected_enrollment_version`, holding the value of the enrollment's `version` the client last observed. A mismatch with the enrollment's current `version` — left behind by an intervening mutation such as a suspension cascade or a prior election change — is rejected with `ERR_STALE_ENROLLMENT_VERSION` (HTTP 412), preventing the client from overwriting state it has not observed.

### 2.8. Plan Status Gating and Nested Resource Resolution

A plan moves through `DRAFT`, `ACTIVE`, `SUSPENDED`, and `TERMINATED`, and its status gates most of the system. Nine operations require the plan to be `ACTIVE` and are otherwise rejected with `ERR_PLAN_NOT_ACTIVE` (HTTP 409): creating an enrollment in the plan, activating an enrollment, declaring a dividend, executing a dividend's reinvestment, creating a purchase window, opening a purchase window, submitting a purchase order, creating a transfer instruction, and executing a transfer instruction. Independently, four operations require the target enrollment to be `ACTIVE` and otherwise fail with `ERR_ENROLLMENT_NOT_ACTIVE` (HTTP 409): recording an initial deposit, changing the participation election, submitting a purchase order, and creating a transfer instruction. Submitting or cancelling a purchase order additionally requires the window to be `OPEN`, failing with `ERR_WINDOW_NOT_OPEN` (HTTP 409) otherwise. Any state-machine trigger attempted from a state where it is not defined — including any action against an entity already in a terminal state, or repeating a transition already taken — is rejected with `ERR_INVALID_STATE` (HTTP 409).

For any request whose path addresses nested resources, path-templated identifiers are resolved strictly left to right, and the request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve, before any later identifier or business rule is examined.

### 2.9. The Share Ledger and Tax-Lot Books

Every movement of shares or cash on an enrollment is recorded as a share ledger entry. Each entry carries the owning `enrollment_id`, an `entry_type` drawn from `INITIAL`, `REINVEST`, `CASH_PAYOUT`, `OCP_PURCHASE`, `FRACTIONAL_SALE`, `WHOLE_SHARE_WITHDRAWAL`, `TRANSFER_OUT`, and `TRANSFER_IN`, a signed four-decimal `quantity` (zero for `CASH_PAYOUT`), a `price_cents` holding the execution or reference price per share where applicable and null otherwise, and a `cash_cents` holding cash paid out — the full payout amount on a `CASH_PAYOUT`, the net proceeds on a `FRACTIONAL_SALE`, and null on every other entry type. Provenance is recorded through `source_type`, one of `DEPOSIT`, `DIVIDEND`, `WINDOW`, `TERMINATION`, or `TRANSFER`, and `source_id`, the id of the originating dividend event, purchase order, or transfer instruction record; for `DEPOSIT` and `TERMINATION` provenance the `source_id` is the id of the owning enrollment itself. Both are plain provenance labels, not foreign keys. An enrollment's `share_balance` is a derived figure: the sum of `quantity` over every ledger entry of the enrollment, kept at four decimal places.

Acquisitions are tracked as tax lots. Each lot records its owning `enrollment_id`, the `acquired_at` timestamp of the acquiring event, the original `quantity` of shares in the lot, the `remaining_quantity` not yet disposed, a `cost_per_share_cents` per-share basis, the original `total_basis_cents` of the lot, and an `acquisition_type` of `INITIAL`, `REINVEST`, `OCP`, or `TRANSFER_IN`. Two carry-over rules apply: a `TRANSFER_IN` lot carries over the per-share basis relieved from the source enrollment's lots, and a `REINVEST` lot's `total_basis_cents` equals the actual cash reinvested rather than a recomputed shares-times-price figure. An enrollment's `total_cost_basis_cents` is computed over its lots that still have shares remaining, taken in creation order: every such lot except the last contributes its `remaining_quantity` multiplied by its `cost_per_share_cents`, rounded half-up to whole cents, and the last such lot contributes its recorded `total_basis_cents` minus the basis already relieved from it, rounded half-up to whole cents — reconciling any rounding remainder on that last lot so the total stays consistent with the lots' recorded basis.

### 2.10. Fee Assessment and Waiver

Every fee the system charges is recorded as a fee assessment on the charged enrollment, carrying the owning `enrollment_id`, a `fee_type` of `ENROLLMENT`, `OCP`, `SALE`, or `TRANSFER`, the `computed_cents` produced by the applicable calculation before any waiver, a `waived` flag defaulting to false, a `waived_reason` that is null while the fee is not waived, and `charged_cents`, which is 0 when the assessment is waived and otherwise equals `computed_cents`. Provenance is recorded through `source_type` — `ACTIVATION`, `WINDOW`, `TERMINATION`, or `TRANSFER` — and `source_id`, again as plain labels rather than foreign keys: for `ACTIVATION` and `TERMINATION` provenance the `source_id` is the charged enrollment's id, for `WINDOW` provenance the purchase order's id, and for `TRANSFER` provenance the transfer instruction's id.

Waiver comes in two forms with different reach. The automatic form applies only to OCP fees: when the participant owning the charged enrollment is fee-waiver-eligible, the OCP assessment is created already waived with `waived_reason` set to `AUTO_ELIGIBLE`. Every other waiver is administrative — a `PlanAdmin` waives an assessment by supplying a `reason`, which is copied into `waived_reason`, and this administrative path is the only way a fee of any other category can be waived.

### 2.11. Validation Order

Incoming requests are checked against a fixed priority order, and a failure at an earlier tier masks every later tier. Authentication comes first (missing or invalid headers, `ERR_UNAUTHENTICATED`), then authorization (role and participant ownership, `ERR_FORBIDDEN`), then left-to-right path-resource existence (`ERR_NOT_FOUND`), then request body shape — required fields present, enum members valid, and numeric ranges sane, such as strictly positive quantities and amounts and the participation-election percentage rules — reported as `ERR_VALIDATION` (HTTP 400). Next come the state gates of §2.8 (`ERR_INVALID_STATE`, `ERR_PLAN_NOT_ACTIVE`, `ERR_WINDOW_NOT_OPEN`, `ERR_ENROLLMENT_NOT_ACTIVE`), then temporal business rules (window schedule sanity, dividend blackout, notice lead time, window opening time), then business constraints (window overlap, duplicate enrollment, election payload shape, minimum purchase amount), then fiscal checks (the cumulative purchase ceiling and sufficient shares for a transfer), and finally referential recipient checks (`ERR_RECIPIENT_NOT_ENROLLED`). A schedule-sanity failure therefore surfaces before an overlap failure on the same request, and a state-gate failure surfaces before either.

Three refinements pin down cases the tier list leaves underdetermined. The optimistic-concurrency check of §2.7 (`ERR_STALE_PLAN_VERSION`, `ERR_STALE_ENROLLMENT_VERSION`) sits between the body-shape tier and the state gates on the two guarded endpoints. Where ownership is a property of a stored resource rather than of the path identifier — enrollment-scoped reads and writes, purchase orders, transfer instructions — that resource must load before ownership can be checked, so a nonexistent identifier yields `ERR_NOT_FOUND` before any ownership question arises; only where the path identifier itself is the ownership key (the participant-record endpoints) does the authorization failure surface first. And on enrollment creation the checked participant identifier arrives in the request body, so the payload's required-field and enum checks surface before the self-enrollment authorization check, which in turn precedes the participant-existence check.

## 3. Business Logic & Workflows

### 3.1. Drafting, Publishing, and Modifying a Plan

Everything begins with a `PlanAdmin` drafting a plan. The creation payload names the issuer through `issuer_name` and `ticker` plus a display `name`, and fixes the plan's economic configuration: `discount_pct`, the fraction knocked off the reference price when dividends are reinvested; `pricing_basis`, either `MARKET_CLOSE` or `FIVE_DAY_AVERAGE`, defaulting to `MARKET_CLOSE` when omitted; `basis_method`, either `FIFO` or `AVERAGE_COST`, defaulting to `FIFO`; the optional-cash-purchase parameters `ocp_min_cents`, `ocp_max_cents`, `ocp_fee_pct`, and `ocp_fee_min_cents`; and the flat fees `sale_fee_cents`, `transfer_fee_cents`, and `enrollment_fee_cents`. Field ranges are enforced identically at creation and at modification: `discount_pct` must be at least 0 and strictly less than 1, `ocp_fee_pct` must be at least 0, and every `_cents` configuration field must be a non-negative integer; violations are `ERR_VALIDATION` (HTTP 400). A new plan starts in `DRAFT` status.

Publishing moves the plan from `DRAFT` to `ACTIVE` and increments its `version`. Only an `ACTIVE` plan accepts the day-to-day traffic enumerated in §2.8. Plans can be listed (optionally filtered by `status`) and read individually by either role.

While a plan lives, a `PlanAdmin` may modify its configuration — the display `name`, `discount_pct`, `pricing_basis`, `basis_method`, the four optional-cash-purchase parameters, and the three flat fees — through the OCC-guarded modification contract of §2.7, which requires `expected_plan_version` and rejects stale writers with `ERR_STALE_PLAN_VERSION`. A successful modification increments the plan's `version`. When the modified plan is `ACTIVE` at the time, the modification additionally auto-creates a `DRAFT` plan notice of type `MODIFICATION` — its `effective_at` set to the logical clock plus ten days and its `message` a fixed informational placeholder — which must still go through the publication flow of §3.7; because the configuration change itself was already applied by the modification, that notice's later taking effect drives no further plan transition.

A plan's endgame is termination, available from either `ACTIVE` or `SUSPENDED`; terminating a plan drags every non-terminal enrollment of the plan through the full termination cascade of §3.9. The plan-termination request may carry an optional `sale_price_cents` — a non-negative integer defaulting to 0 — used as the fractional-sale price of every cascaded enrollment. Suspension and resumption, and the notice-driven paths into them, are covered in §3.7.

### 3.2. Participants, Enrollment, and Participation Elections

A `PlanAdmin` registers each investor as a participant, supplying `full_name` and `email` — the email must be unique across participants, and a duplicate is rejected with `ERR_VALIDATION` (HTTP 400) — and optionally setting `fee_waiver_eligible`, which defaults to false and, when true, causes OCP fees for that participant's enrollments to be automatically waived (§2.10).

From there the investor self-enrolls: a `Participant` submits an enrollment into an `ACTIVE` plan with a payload carrying their own `participant_id`, an `election` of `FULL_REINVEST`, `PARTIAL_REINVEST`, or `CASH_ONLY`, and — only for `PARTIAL_REINVEST` — a `reinvest_pct`. The election payload rules are strict and violations are rejected with `ERR_INVALID_ELECTION` (HTTP 422): when the election is `PARTIAL_REINVEST`, `reinvest_pct` must be present and strictly greater than zero and strictly less than one; for either other election, `reinvest_pct` must be absent entirely. One participant may hold only one non-terminal enrollment per plan — a second enrollment while one exists in `PENDING`, `ACTIVE`, or `SUSPENDED` is rejected with `ERR_ALREADY_ENROLLED` (HTTP 409). The created enrollment records its owner through `participant_id` and the plan it belongs to through its `plan_id`, and it starts in `PENDING` with a `share_balance` of 0.0000 and a `total_cost_basis_cents` of 0.

Activation is an administrative act: a `PlanAdmin` activates a `PENDING` enrollment of an `ACTIVE` plan, moving it to `ACTIVE`. Activation assesses the one-time enrollment fee — a fee assessment of type `ENROLLMENT` whose `computed_cents` equals the plan's `enrollment_fee_cents`, recorded with `ACTIVATION` provenance — and increments the enrollment's `version`.

The owner may later change their participation election on an `ACTIVE` enrollment (any other enrollment status fails with `ERR_ENROLLMENT_NOT_ACTIVE`). The change request carries the new `election`, the conditionally required `reinvest_pct` under the same rules as enrollment, and the mandatory `expected_enrollment_version` of §2.7, with a stale value rejected as `ERR_STALE_ENROLLMENT_VERSION`. A successful change increments the enrollment's `version`. A participant's enrollments can be listed under their participant record, a plan's enrollments can be listed by an administrator with an optional `status` filter, and a single enrollment can be read by its owner or an administrator.

### 3.3. Seeding an Account: Initial Deposits and Position Reporting

An enrollment that already holds shares outside the plan is seeded by a `PlanAdmin` recording an initial share deposit into it. The enrollment must be `ACTIVE`, and the deposit payload carries the deposited `quantity` and the `cost_per_share_cents` at which those shares entered. The deposit creates an `INITIAL` ledger entry — positive `quantity`, `price_cents` set to the supplied cost, provenance `DEPOSIT` — alongside an `INITIAL` tax lot whose `total_basis_cents` is the deposited quantity times the supplied per-share cost, rounded half-up to whole cents, and then recomputes the enrollment's derived position: `share_balance` becomes the sum of ledger quantities per §2.9, and `total_cost_basis_cents` is recomputed per the tax-lot aggregation of §2.9. Recording a deposit increments the enrollment's `version` and returns the created ledger entry.

Positions are read back through the enrollment's books. The share-and-cash movement log can be listed with an optional `entry_type` filter, the tax lots can be listed in full, and the fee history of §3.6 can be listed with a `fee_type` filter — each visible to the owning participant or an administrator.

### 3.4. Dividend Processing: Declaration, Pricing, Reinvestment, Settlement

A `PlanAdmin` declares a dividend on an `ACTIVE` plan by supplying `amount_per_share_cents` — the declared dividend per share in whole cents — together with the `record_date` and `payable_date`. The event starts in `DECLARED`. Dividends of a plan can be listed with an optional `status` filter.

Pricing comes next: the administrator supplies both candidate reference prices, `closing_price_cents` and `avg5_price_cents`, and the system selects between them according to the plan's `pricing_basis` — the closing price for `MARKET_CLOSE`, the five-day average for `FIVE_DAY_AVERAGE`. The discounted reinvestment price is then the selected reference multiplied by one minus the plan's `discount_pct`, rounded half-up to whole cents, and stored as `reinvestment_price_cents`. Per §2.5 this price rounding happens before any share division. The two bases are genuinely divergent variants: identical dividend data yields a different `reinvestment_price_cents`, and therefore a different reinvested share count, under `FIVE_DAY_AVERAGE` than under `MARKET_CLOSE`. Pricing moves the event from `DECLARED` to `PRICED` and increments its `version`.

Execution runs the reinvestment, moving the event from `PRICED` to `REINVESTED`. It is permitted only while the plan is `ACTIVE` (otherwise `ERR_PLAN_NOT_ACTIVE`) and only once the logical clock has reached the `payable_date` (an earlier attempt fails with `ERR_INVALID_STATE`, HTTP 409). For every enrollment of the plan that is `ACTIVE` at execution time and holds at least one record-date-eligible share, the system proceeds as follows. Eligible shares are the sum of ledger entry quantities recorded at or before the end of the `record_date` — 23:59:59.999 UTC — holders of record at the end of that date. The total dividend cash is the eligible shares times `amount_per_share_cents`, rounded half-up to whole cents. That total is then split according to the enrollment's `election`: under `FULL_REINVEST` the entire total is reinvested and the cash payout is zero; under `CASH_ONLY` nothing is reinvested and the entire total pays out in cash; under `PARTIAL_REINVEST` the reinvested portion is the total times `reinvest_pct`, rounded half-up to whole cents first, and the cash payout is the remainder — so the two portions always sum exactly back to the total. The reinvested shares are the reinvested cash divided by the stored `reinvestment_price_cents`, rounded half-up to four decimal places. Each reinvestment writes a `REINVEST` ledger entry (positive quantity at the reinvestment price, `DIVIDEND` provenance naming the dividend event) and a `REINVEST` tax lot whose `quantity` is the reinvested shares, whose `cost_per_share_cents` is the reinvestment price, and whose `total_basis_cents` is the actual cash reinvested — not the shares-times-price product. The cash portion writes a `CASH_PAYOUT` entry whose `quantity` is 0 and whose `cash_cents` is the full cash amount (the entire dividend when the election is `CASH_ONLY`). A zero-sized portion writes nothing: under `FULL_REINVEST` no `CASH_PAYOUT` entry is created, and under `CASH_ONLY` no `REINVEST` entry or tax lot is created. Because execution requires the plan to be `ACTIVE`, suspended enrollments are unreachable at this step. Execution increments the event's `version`, and a final administrative step moves the event from `REINVESTED` to `SETTLED`, incrementing `version` again. While a dividend event is anywhere short of `SETTLED`, it casts a purchase-window blackout per §3.5.

### 3.5. Optional Cash Purchases: Windows, Orders, and Settlement

Optional cash purchases run through scheduled windows. A `PlanAdmin` creates a window on an `ACTIVE` plan by supplying `opens_at`, `closes_at`, and the fixed `price_cents` at which every order in the window will execute; the window starts `SCHEDULED`. Creation enforces three distinct checks. Schedule sanity: the opening instant must be strictly earlier than the closing instant, and the opening instant must be at or after the logical clock — no window may open in the past — else `ERR_WINDOW_SCHEDULE_INVALID` (HTTP 422). Dividend blackout: the window must not intersect the blackout cast by any non-`SETTLED` dividend event of the same plan, where a blackout is the closed interval from 00:00:00 UTC two days before the dividend's `record_date` through the end of its `payable_date` — 23:59:59.999 UTC — and touching either blackout boundary already counts as intersection — violations fail with `ERR_WINDOW_DIVIDEND_BLACKOUT` (HTTP 422). Window overlap: the new window's half-open interval, inclusive of `opens_at` and exclusive of `closes_at`, must not intersect any existing non-`SETTLED` window of the same plan, though back-to-back adjacency — one window closing exactly when the other opens — is allowed; violations fail with `ERR_WINDOW_OVERLAP` (HTTP 422). Windows can be listed per plan, with an optional `status` filter, and read individually.

A `SCHEDULED` window is opened by an administrator once the plan is `ACTIVE` and the logical clock sits at or after `opens_at` but strictly before `closes_at`; an opening attempt outside that half-open interval fails with `ERR_WINDOW_OPEN_TOO_EARLY` (HTTP 422). Opening moves the window to `OPEN` and increments its `version`. Once the clock has reached `closes_at`, an administrator closes the window, moving it from `OPEN` to `CLOSED` with another `version` increment; a close attempt before the clock has reached `closes_at` fails with `ERR_INVALID_STATE` (HTTP 409).

While a window is `OPEN`, a `Participant` submits optional cash purchase orders into it with a payload naming their `enrollment_id` and the `amount_cents` to invest. Submission is refused when the window is not `OPEN` (`ERR_WINDOW_NOT_OPEN`), when the enrollment is not `ACTIVE` (`ERR_ENROLLMENT_NOT_ACTIVE`), or when the plan is not `ACTIVE` (`ERR_PLAN_NOT_ACTIVE`). Two amount checks then apply in §2.11 order: the amount must be at least the plan's `ocp_min_cents`, else `ERR_PURCHASE_BELOW_MIN` (HTTP 422); and the cumulative ceiling — the sum of `amount_cents` over that enrollment's still-`SUBMITTED` orders in the same window, plus the new amount — must not strictly exceed the plan's `ocp_max_cents`, else `ERR_PURCHASE_LIMIT_EXCEEDED` (HTTP 422). Landing exactly on the ceiling is allowed, and orders that leave `SUBMITTED` release their reservation. A new order starts `SUBMITTED`, and its amount is added to the window's `submitted_total_cents`, a derived figure reconciled on every order mutation. Orders can be read individually by owner or administrator, listed per window by an administrator, or listed across windows with optional `enrollment_id`, `window_id`, and `status` filters.

The owner may cancel an order while it is `SUBMITTED` and its window is still `OPEN`; cancellation moves it to `CANCELLED`, removes its amount from the window's `submitted_total_cents`, and increments the order's `version`. A plan suspension instead forces still-`SUBMITTED` orders to `REJECTED` through the cascade of §3.7, likewise releasing their amounts.

Settlement is the final step: an administrator settles a `CLOSED` window, moving it to `SETTLED`. For every still-`SUBMITTED` order of the window the system first assesses the OCP fee — the greater of the plan's `ocp_fee_min_cents` floor and the proportional fee, the latter being the order's `amount_cents` times the plan's `ocp_fee_pct` rounded half-up to whole cents — as a fee assessment of type `OCP` with `WINDOW` provenance. When the participant behind the enrollment is fee-waiver-eligible the assessment is created waived with `waived_reason` `AUTO_ELIGIBLE` and `charged_cents` 0; otherwise `charged_cents` equals the computed fee. The order then moves to `SETTLED` with `settled_shares` set to the fee-net amount — `amount_cents` minus `charged_cents` — divided by the window's `price_cents`, rounded half-up to four decimal places; `settled_shares` is null until settlement. Settlement also writes an `OCP_PURCHASE` ledger entry (positive quantity at the window price, `WINDOW` provenance naming the order) and an `OCP` tax lot whose per-share basis is the window's `price_cents` and whose `total_basis_cents` is the fee-net amount — `amount_cents` minus `charged_cents`. Settling the window increments its `version`, and each settled order's `version` increments as well.

### 3.6. Fee Assessments and Administrative Waiver

The four fee categories surface at distinct moments: `ENROLLMENT` at enrollment activation (§3.2), `OCP` at window settlement (§3.5), `SALE` at termination (§3.9), and `TRANSFER` at transfer execution (§3.8). Every assessment records its `computed_cents` before waiver and its final `charged_cents` after, per §2.10. The automatic waiver exists only for OCP fees of fee-waiver-eligible participants; every other fee can be waived only administratively.

Administrative waiver is a `PlanAdmin` act on an individual assessment, supplying a `reason`. Waiving sets `waived` to true, copies the supplied reason into `waived_reason`, zeroes `charged_cents`, and increments the assessment's `version`. Waiving is not guarded by the assessment's current state: an already-waived assessment may be waived again, overwriting `waived_reason`. An enrollment's assessments can be listed with an optional `fee_type` filter.

### 3.7. Plan Communications, Suspension, and Resumption

Material plan changes are communicated through notices. A `PlanAdmin` drafts a notice on a plan with a `notice_type` of `MODIFICATION`, `SUSPENSION`, or `TERMINATION`, an `effective_at` instant, and a free-text `message`; the notice starts in `DRAFT`. Notices of a plan can be listed with optional `notice_type` and `status` filters. Publication moves a notice from `DRAFT` to `PUBLISHED` and stamps `published_at`, but only when at least ten full days separate the logical clock from `effective_at`; a shorter lead fails with `ERR_NOTICE_LEAD_TIME_SHORT` (HTTP 422). Once the clock reaches `effective_at`, the administrator takes the notice into effect, moving it from `PUBLISHED` to `EFFECTIVE`; a take-effect attempt before the clock has reached `effective_at` fails with `ERR_INVALID_STATE` (HTTP 409). What happens then depends on the type: a `SUSPENSION` notice drives the plan's `ACTIVE` → `SUSPENDED` transition with its full cascade (guarded — the plan must be `ACTIVE`), a `TERMINATION` notice drives the plan into `TERMINATED` with its full cascade — settling fractional remainders at a sale price of 0 cents — and a `MODIFICATION` notice drives nothing, since the configuration change was already applied by the modification itself (§3.1). Publication and taking effect each increment the notice's `version`.

Suspension — whether invoked directly by an administrator or delivered through a `SUSPENSION` notice — moves an `ACTIVE` plan to `SUSPENDED` and cascades. Every `ACTIVE` enrollment of the plan moves to `SUSPENDED`, each such enrollment's still-`SUBMITTED` purchase orders move to `REJECTED`, and each rejection removes the order's amount from its window's `submitted_total_cents`. The plan's `version` increments, and each cascaded enrollment's and order's `version` increments with its own mutation.

Resumption moves a `SUSPENDED` plan back to `ACTIVE` and restores every `SUSPENDED` enrollment of the plan to `ACTIVE`. The compensation is deliberately asymmetric: orders rejected by the suspension are not restored and remain `REJECTED`. Plan termination, from `ACTIVE` or `SUSPENDED`, moves the plan to `TERMINATED` and runs every non-terminal enrollment of the plan through the termination cascade of §3.9.

### 3.8. Transfers and Gifts of Plan Shares

An investor moves shares out of their account through a transfer instruction. The owning `Participant` creates one against their `ACTIVE` source enrollment — the plan must be `ACTIVE` as well — with a payload carrying a `transfer_type`, a strictly positive four-decimal `quantity`, and the counterpart details. For `TRANSFER`, an in-plan move to another enrollment, `recipient_enrollment_id` is required and `recipient_name` and `recipient_address` must be null. For `GIFT`, where shares leave the plan to an external recipient, `recipient_enrollment_id` must be null and `recipient_name` and `recipient_address` are required as non-empty strings. Violations of these counterpart payload rules are rejected with `ERR_RECIPIENT_NOT_ENROLLED` (HTTP 422), not `ERR_VALIDATION`. Two further checks guard creation: the quantity must not exceed the source enrollment's `share_balance`, else `ERR_INSUFFICIENT_SHARES` (HTTP 422); and a `TRANSFER`'s recipient enrollment must exist, belong to the same plan, and be `ACTIVE`, else `ERR_RECIPIENT_NOT_ENROLLED` (HTTP 422). A new instruction starts `SUBMITTED`. Instructions sourced from an enrollment can be listed with a `status` filter, an administrator can list instructions filtered by `recipient_enrollment_id`, `source_enrollment_id`, or `status`, and a single instruction can be read by the source owner or an administrator.

Execution is administrative. A `PlanAdmin` executes a `SUBMITTED` instruction, supplying `fmv_per_share_cents` — the fair market value per share, which stays null until execution. Execution re-verifies its world: the source enrollment and the plan must both be `ACTIVE`, the source's `share_balance` must still cover the quantity (the sufficient-shares check is repeated here and again fails with `ERR_INSUFFICIENT_SHARES`), and for `TRANSFER` the recipient must still be an `ACTIVE` enrollment of the same plan. The effects are several. A `TRANSFER_OUT` ledger entry is written on the source enrollment — negative `quantity`, `price_cents` set to the fair market value, `TRANSFER` provenance naming the instruction. The source's tax lots are relieved for the disposed quantity under the plan's `basis_method`, exactly as specified in §3.9. For `TRANSFER`, a `TRANSFER_IN` ledger entry with the positive quantity and `price_cents` set to the fair market value is written on the recipient enrollment, and a `TRANSFER_IN` tax lot is created carrying over the basis that relief took from the source lots: its `cost_per_share_cents` is the total relieved basis divided by the transferred quantity, rounded half-up to whole cents, and its `total_basis_cents` is the total relieved basis. For `GIFT`, no recipient entry exists and the disposition is reported at `fmv_per_share_cents`. Finally, a fee assessment of type `TRANSFER` with `TRANSFER` provenance is created on the source enrollment with `computed_cents` equal to the plan's `transfer_fee_cents`, waivable only administratively. A successful execution moves the instruction from `SUBMITTED` to `EXECUTED`, stamps `executed_at`, and increments the instruction's `version`.

The source owner may cancel a `SUBMITTED` instruction at any time before execution; cancellation moves it to `CANCELLED` and increments its `version`.

### 3.9. Termination Settlement, Basis Relief, and Tax Reporting

Terminating an enrollment — by the owning `Participant` or a `PlanAdmin`, from `ACTIVE` or `SUSPENDED` — settles the position in cash and shares. The request must supply `sale_price_cents`, a strictly positive integer holding the price at which the fractional remainder is sold. Settlement splits the enrollment's `share_balance` into a whole-share part, the integer floor of the balance, and a fractional part, the balance minus that floor rounded half-up to four decimal places. The boundary is exact: when the fractional part is exactly 0.0000, no fractional-sale entry is created and no sale fee is assessed at all. When the fractional part is greater than zero, the gross proceeds are the fractional shares times `sale_price_cents`, rounded half-up to whole cents first; the sale fee is the plan's `sale_fee_cents`, recorded as a `SALE` assessment with `TERMINATION` provenance and waivable only administratively; and the net proceeds are the rounded gross minus the fee. A `FRACTIONAL_SALE` ledger entry records the movement — negative fractional quantity, `price_cents` set to the sale price, `cash_cents` set to the net proceeds, `TERMINATION` provenance. Whenever the whole-share part is greater than zero, a `WHOLE_SHARE_WITHDRAWAL` entry is written with the negative whole quantity and null `price_cents` and `cash_cents`. All of the enrollment's tax lots are then relieved in full for the disposed quantity, leaving every lot's `remaining_quantity` at 0, and the enrollment's `terminated_at` is stamped and its `version` incremented. Plan-level termination runs this same cascade on every non-terminal enrollment of the plan.

Basis relief — here and at transfer execution — follows the plan's `basis_method`, and the two variants diverge in both result and mechanics. Under `FIFO`, lots are relieved oldest first, ordered by `acquired_at` ascending with ties broken by creation timestamp ascending; relief takes from each lot the lesser of what is still needed and that lot's `remaining_quantity`, continuing until the disposed quantity is covered. The basis leaving the enrollment is the sum over the touched lots of each taken quantity times that lot's `cost_per_share_cents`, rounded half-up to whole cents — except that when a lot is fully consumed, its contribution is that lot's original `total_basis_cents` minus whatever basis was already relieved from it, so repeated relief never drifts from the lot's recorded basis. Under `AVERAGE_COST`, a single weighted-average cost is computed once, before any relief, across all lots with shares remaining: the sum over those lots of `remaining_quantity` times `cost_per_share_cents`, divided by the total remaining quantity, rounded half-up to whole cents. The basis leaving the enrollment is then the disposed quantity times that average, rounded half-up to whole cents, and every lot is relieved pro-rata — each loses the disposed quantity times its share of the total remaining, rounded half-up to four decimal places — with the oldest lot absorbing any four-decimal rounding residue. Identical lots and an identical disposed quantity yield a different relieved basis, and therefore a different reported gain, under the two methods.

The annual tax report assembles these figures for a requested `year` — a required integer query parameter, with a missing or non-integer value rejected as `ERR_VALIDATION` (HTTP 400) — returning that `year`, the year's `dividends_cents`, and the year's disposition totals — `proceeds_cents`, `basis_cents`, and `gain_cents` — computed under the plan's basis method, plus the `basis_method` in force. The `dividends_cents` figure is the sum of the full dividend cash — the reinvested plus the paid-out portions — of every dividend executed for the enrollment whose `payable_date` falls in the requested year; a dividend that was declared but never executed contributes nothing. Each disposition is attributed to the logical-clock year in which it was executed, and its gain is its proceeds minus the basis relieved: proceeds are the disposed quantity times the applicable per-share price — the fair market value at transfer execution or the sale price at termination — rounded half-up to whole cents, and the relieved basis comes from the relief rules above. At termination only the fractional sale is a reportable disposition; the whole-share withdrawal produces no proceeds and no tax-report entry.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code. Operations that modify an existing resource or drive a state transition return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/drip/plans` | Create a plan (starts `DRAFT`) | PlanAdmin |
| GET | `/drip/plans` | List plans | PlanAdmin, Participant |
| GET | `/drip/plans/{id}` | Get one plan | PlanAdmin, Participant |
| PATCH | `/drip/plans/{id}` | Modify plan configuration (OCC-guarded) | PlanAdmin |
| POST | `/drip/plans/{id}/publish` | Publish a draft plan | PlanAdmin |
| POST | `/drip/plans/{id}/suspend` | Suspend an active plan with cascade | PlanAdmin |
| POST | `/drip/plans/{id}/resume` | Resume a suspended plan | PlanAdmin |
| POST | `/drip/plans/{id}/terminate` | Terminate a plan and its enrollments | PlanAdmin |
| POST | `/drip/participants` | Register a participant | PlanAdmin |
| GET | `/drip/participants/{id}` | Get one participant | PlanAdmin, Participant |
| GET | `/drip/participants/{id}/enrollments` | List enrollments of a participant | PlanAdmin, Participant |
| POST | `/drip/plans/{plan_id}/enrollments` | Enroll the acting participant | Participant |
| GET | `/drip/plans/{id}/enrollments` | List enrollments of a plan | PlanAdmin |
| GET | `/drip/enrollments/{id}` | Get one enrollment | PlanAdmin, Participant |
| POST | `/drip/enrollments/{id}/activate` | Activate a pending enrollment | PlanAdmin |
| PATCH | `/drip/enrollments/{id}/election` | Change participation election (OCC-guarded) | Participant |
| POST | `/drip/enrollments/{id}/terminate` | Terminate an enrollment and settle its position | PlanAdmin, Participant |
| POST | `/drip/enrollments/{enrollment_id}/deposits` | Record an initial share deposit | PlanAdmin |
| GET | `/drip/enrollments/{id}/ledger-entries` | List share/cash movements of an enrollment | PlanAdmin, Participant |
| GET | `/drip/enrollments/{id}/tax-lots` | List tax lots of an enrollment | PlanAdmin, Participant |
| GET | `/drip/enrollments/{id}/fees` | List fee assessments of an enrollment | PlanAdmin, Participant |
| GET | `/drip/enrollments/{id}/transfers` | List transfer instructions sourced from an enrollment | PlanAdmin, Participant |
| GET | `/drip/enrollments/{enrollment_id}/tax-report` | Get the per-year tax report of an enrollment | PlanAdmin, Participant |
| POST | `/drip/fee-assessments/{id}/waive` | Administratively waive a fee assessment | PlanAdmin |
| POST | `/drip/plans/{plan_id}/dividend-events` | Declare a dividend | PlanAdmin |
| GET | `/drip/plans/{id}/dividend-events` | List dividends of a plan | PlanAdmin, Participant |
| POST | `/drip/dividend-events/{id}/price` | Price a declared dividend | PlanAdmin |
| POST | `/drip/dividend-events/{id}/execute` | Run reinvestment for a priced dividend | PlanAdmin |
| POST | `/drip/dividend-events/{id}/settle` | Settle a reinvested dividend | PlanAdmin |
| POST | `/drip/plans/{plan_id}/purchase-windows` | Create an optional cash purchase window | PlanAdmin |
| GET | `/drip/plans/{id}/purchase-windows` | List windows of a plan | PlanAdmin, Participant |
| GET | `/drip/purchase-windows/{id}` | Get one window | PlanAdmin, Participant |
| POST | `/drip/purchase-windows/{id}/open` | Open a scheduled window | PlanAdmin |
| POST | `/drip/purchase-windows/{id}/close` | Close an open window | PlanAdmin |
| POST | `/drip/purchase-windows/{id}/settle` | Settle a closed window and its orders | PlanAdmin |
| POST | `/drip/purchase-windows/{window_id}/purchase-orders` | Submit an optional cash purchase order | Participant |
| GET | `/drip/purchase-windows/{id}/purchase-orders` | List orders of a window | PlanAdmin |
| GET | `/drip/purchase-orders/{id}` | Get one order | PlanAdmin, Participant |
| GET | `/drip/purchase-orders` | List orders with filters | PlanAdmin, Participant |
| POST | `/drip/purchase-orders/{id}/cancel` | Cancel a submitted order | Participant |
| POST | `/drip/plans/{plan_id}/notices` | Create a plan communication notice | PlanAdmin |
| GET | `/drip/plans/{id}/notices` | List notices of a plan | PlanAdmin, Participant |
| POST | `/drip/notices/{id}/publish` | Publish a draft notice | PlanAdmin |
| POST | `/drip/notices/{id}/take-effect` | Take a published notice into effect | PlanAdmin |
| POST | `/drip/enrollments/{enrollment_id}/transfers` | Create a transfer or gift instruction | Participant |
| GET | `/drip/transfer-instructions/{id}` | Get one transfer instruction | PlanAdmin, Participant |
| GET | `/drip/transfer-instructions` | List transfer instructions with filters | PlanAdmin |
| POST | `/drip/transfer-instructions/{id}/execute` | Execute a transfer instruction | PlanAdmin |
| POST | `/drip/transfer-instructions/{id}/cancel` | Cancel a submitted instruction | Participant |
| POST | `/drip/_clock/set_current_utc` | Set the logical clock | PlanAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_PLAN_NOT_ACTIVE` | 409 |
| `ERR_WINDOW_NOT_OPEN` | 409 |
| `ERR_ENROLLMENT_NOT_ACTIVE` | 409 |
| `ERR_WINDOW_SCHEDULE_INVALID` | 422 |
| `ERR_WINDOW_DIVIDEND_BLACKOUT` | 422 |
| `ERR_NOTICE_LEAD_TIME_SHORT` | 422 |
| `ERR_WINDOW_OPEN_TOO_EARLY` | 422 |
| `ERR_WINDOW_OVERLAP` | 422 |
| `ERR_ALREADY_ENROLLED` | 409 |
| `ERR_INVALID_ELECTION` | 422 |
| `ERR_PURCHASE_BELOW_MIN` | 422 |
| `ERR_PURCHASE_LIMIT_EXCEEDED` | 422 |
| `ERR_INSUFFICIENT_SHARES` | 422 |
| `ERR_RECIPIENT_NOT_ENROLLED` | 422 |
| `ERR_STALE_PLAN_VERSION` | 412 |
| `ERR_STALE_ENROLLMENT_VERSION` | 412 |
