# Corporate Trustee Indenture API — Product Requirements Document

## 1. Introduction

Corporate trust departments sit between bond issuers and their noteholders, administering the indenture that governs a debt issuance for its entire life: watching the covenant calendar, collecting compliance certificates, acting as payment agent for interest and principal, policing collateral, and — when things go wrong — declaring defaults and soliciting noteholder direction. Each of these duties carries fiduciary exposure, and each is traditionally tracked across spreadsheets, email threads, and disparate ledgers. This document specifies an API that consolidates the full indenture administration workflow into a single, auditable system of record.

The platform serves a corporate trust operations team with strict segregation of duties: officers draft and verify, managers confirm and decide, and no individual may perform both halves of a sensitive step pair. Issuers interact with the system to fund distributions and submit compliance evidence; noteholders interact to endorse directions and cast consent ballots. Because the domain is driven by calendar events — covenant due dates, payment dates, cure deadlines, circulation windows — the system maintains a controllable logical clock rather than relying on wall-clock time, and every clock advance triggers a deterministic sweep of time-based transitions and their cascades.

The requirements below are written for the engineering team building this API. Global contracts (envelope, pagination, concurrency, precision) appear in §2; the business workflows, including every state machine, calculation, and validation rule, appear in §3; §4 and §5 summarize the endpoint and error catalogues.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply uniformly to every resource and endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The system recognizes exactly five roles: `PlatformAdmin`, `TrustOfficer`, `TrustManager`, `Issuer`, and `Noteholder`. A request whose `X-User-Role` header is missing or does not name one of these five roles is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is valid but not permitted on the target endpoint per §4 is rejected with `ERR_FORBIDDEN` (HTTP 403).

Role identity semantics differ by role and are part of the contract:

- When `X-User-Role` is `Noteholder`, `X-User-ID` is the `id` of the acting `NoteholderAccount`; ownership checks on any operation that names a `noteholder_account_id` compare that value to `X-User-ID`, and a mismatch is rejected with `ERR_OWNERSHIP_VIOLATION` (HTTP 403).
- When `X-User-Role` is `Issuer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity's `id`. Issuer ownership is instead established field-wise: the issuer owns exactly those indentures whose `issuer_ref` equals `X-User-ID`, and issuer-scoped operations on an indenture the caller does not own are rejected with `ERR_OWNERSHIP_VIOLATION` (HTTP 403).
- When `X-User-Role` is `PlatformAdmin`, `TrustOfficer`, or `TrustManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it on resources where a workflow requires attribution (for example, as `declared_by_user_id` on a `DefaultCase`, `reviewed_by_user_id` on a `CovenantCertificate`, `verified_by_user_id` on a `CollateralReleaseRequest`, `drafted_by_user_id` on a `FeeInvoice`, or the confirming, deciding, and issuing counterparts on those same families), but it never compares the header to any entity's `id`.

Ownership enforcement applies to every operation where an `Issuer` or `Noteholder` acts on scoped resources: submitting a covenant certificate, funding a payment run, creating or revoking a consent solicitation, requesting a collateral release, paying or disputing a fee invoice, endorsing a direction, withdrawing an endorsement, and casting a ballot.

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items skipped and defaults to 0.

Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order.

The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`. List endpoints additionally accept filter query parameters named after the resource's own attributes and foreign keys — for example `status`, `issuer_ref`, `indenture_id`, `tranche_id`, `noteholder_account_id`, `covenant_obligation_id`, `funding_status`, `distribution_status`, `payment_run_id`, `position_id`, `default_case_id`, `direction_id`, `collateral_item_id`, and `invoice_type` — each narrowing the result set to rows matching the supplied value.

### 2.4. Common Resource Properties

All sixteen resources in this system — `Indenture`, `Tranche`, `NoteholderAccount`, `Position`, `CovenantObligation`, `CovenantCertificate`, `PaymentRun`, `DistributionRecord`, `DefaultCase`, `NoteholderDirection`, `DirectionEndorsement`, `ConsentSolicitation`, `CollateralItem`, `CollateralReleaseRequest`, `FeeInvoice`, and `TrusteeAppointment` — share one standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by one on every mutation of the resource.

A mutation for these purposes includes system-driven cascades: when a cascade changes a resource (for example, a payment run moving from `SCHEDULED` to `SUSPENDED` because its indenture defaulted), that resource's `updated_at` refreshes and its `version` increments just as if a client had written to it directly.

### 2.5. The Logical Clock and the Time-Driven Sweep

The system never reads wall-clock time. A logical clock governs every temporal rule in this document — due dates, grace periods, cure deadlines, circulation windows, valuation freshness, settlement timing, and effectiveness dates. At server startup, before any client intervention, the logical clock reads exactly `2026-05-01T00:00:00Z`.

A `PlatformAdmin` advances the clock through an admin-only capability that accepts a target instant `to_iso8601` and returns the resulting `current_utc`. Each clock set triggers a deterministic **system sweep**: covenant obligations whose due dates have passed transition `OPEN` → `LATE` and, after their grace period, `LATE` → `BREACHED`; indenture covenant postures are recomputed; breach-triggered default cases are auto-created; circulating noteholder directions whose circulation deadline has passed transition to `LAPSED`; and due distribution records settle. Every cascade that follows from these transitions (payment suspension, record holding, posture changes, and the like) executes as part of the same sweep. The business meaning of each swept transition is specified in §3.

### 2.6. Monetary Precision, Rounding, and Basis-Point Arithmetic

All monetary quantities are integers denominated in cents — field names ending in `_cents` — and all monetary arithmetic is exact integer arithmetic. Where a calculation produces a fractional cent, the rounding rule is **round half up to a whole cent**, applied at the step the relevant §3 rule specifies (per position before summation for interest; per tier before summation for extraordinary fees). Percentages and rates are expressed in integer basis points (`interest_rate_bps`, `consent_threshold_bps`, `post_release_coverage_bps`); one hundred basis points equal one percent, and ten thousand basis points equal one hundred percent. Threshold comparisons that would otherwise require division are performed by integer cross-multiplication — multiplying each side by the opposite denominator — so no floating-point division ever participates in a pass/fail decision. The single division that does occur, the final coverage division in the collateral calculation, rounds **down** (floor) to a whole basis point.

### 2.7. Optimistic Concurrency Control

Three creation endpoints are guarded by optimistic concurrency control, because each of them supersedes an in-flight sibling on a parent resource and must therefore not be built on a stale view of that parent. Each guarded request carries a non-optional field naming the caller's last-observed `version` of the parent entity; if that value does not match the parent entity's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from superseding a sibling it has never observed.

- A `POST /trustee-appointments` request must carry `expected_indenture_version` matching the target indenture's current `version`. Because creating an appointment supersedes any in-flight appointment on the same indenture (and advances the indenture's version), a writer whose view predates another writer's appointment is stale and is rejected with `ERR_STALE_VERSION`.
- A `POST /collateral-release-requests` request must carry `expected_collateral_item_version` matching the target collateral item's current `version`. Because creating a request supersedes any `SUBMITTED` request on the same item (and advances the item's version), a stale view is rejected with `ERR_STALE_VERSION`.
- A `POST /directions` request must carry `expected_default_case_version` matching the target default case's current `version`. Because creating a direction supersedes any `CIRCULATING` direction on the same case (and advances the case's version), a stale view is rejected with `ERR_STALE_VERSION`.

No other endpoint takes a version field; all other mutations proceed without an OCC check.

### 2.8. Validation Discipline and Evaluation Order

Every request is validated against an ordered rule stack, and when several rules are violated at once the rejection carries the error of the **earliest** rule in the stack. The evaluation order is fixed:

1. Authentication: the `X-User-Role` header is present and names a declared role — `ERR_UNAUTHENTICATED`.
2. Authorization: the role is permitted on the endpoint — `ERR_FORBIDDEN`.
3. Ownership: a `Noteholder` acts only on its own account and an `Issuer` acts only on indentures it owns — `ERR_OWNERSHIP_VIOLATION`.
4. Existence: every path identifier and every referenced `*_id` in the payload resolves to an existing resource — `ERR_NOT_FOUND`.
5. State admissibility: the target resource's state admits the operation — `ERR_INVALID_STATE`; writes against a terminal state are rejected as `ERR_ALREADY_TERMINAL`; payment execution while the indenture is not `ACTIVE` is rejected as `ERR_INDENTURE_NOT_ACTIVE`.
6. Segregation of duties on the three sensitive step pairs (declare/confirm, verify/decide, draft/issue): the completing actor's `X-User-ID` must differ from the originating actor recorded on the resource — `ERR_SEGREGATION_OF_DUTIES`.
7. Default lock on collateral decisions — `ERR_DEFAULT_LOCK`.
8. Extraordinary-service basis on fee drafting — `ERR_NO_EXTRAORDINARY_BASIS`.
9. Uniqueness constraints — `ERR_DUPLICATE_CONSTRAINT`.
10. Interest-window occupation — `ERR_PERIOD_OVERLAP`.
11. Solicitation-window occupation — `ERR_SOLICITATION_WINDOW_OVERLAP`.
12. Aggregate position principal — `ERR_PRINCIPAL_EXCEEDS_POSITION`.
13. Collateral coverage floor — `ERR_COVERAGE_BELOW_MINIMUM`.
14. Redemption notice period — `ERR_NOTICE_PERIOD_SHORT`.
15. Cure deadline — `ERR_CURE_DEADLINE_PASSED`.
16. Direction circulation window — `ERR_DIRECTION_LAPSED`.
17. Solicitation expiry — `ERR_SOLICITATION_EXPIRED`.
18. Collateral valuation freshness — `ERR_VALUATION_STALE`.
19. Appointment effectiveness — `ERR_NOT_YET_EFFECTIVE`.
20. Funding sufficiency — `ERR_FUNDING_SHORTFALL`.
21. Ratio covenant pass — `ERR_COVENANT_RATIO_FAILED`.
22. Waiver target obligation — `ERR_TARGET_OBLIGATION_MISMATCH`.
23. Holder-of-record eligibility and substitution-field freshness — `ERR_NO_ELIGIBLE_POSITION`.
24. Substitution field presence — `ERR_SUBSTITUTE_REQUIRED`.
25. Direction effectiveness at execution — `ERR_THRESHOLD_NOT_MET`.
26. Request shape: required fields present, enum values valid, dates well-formed ISO — `ERR_INVALID_REQUEST`. This category includes an `INTEREST` run missing its period dates, a redemption run missing its principal target, and a ratio-type covenant obligation missing its threshold fields. Shape validation is deliberately last: a request that is both malformed and, say, unauthorized reports the authorization failure.

The concrete trigger conditions for rules 5 through 25 are specified in §3 alongside the workflows they guard; the catalogue in §5 lists identifiers and statuses only.

### 2.9. Nested Resource Retrieval and Reference Resolution

Requests that address resources through nested paths or through foreign-key references in the payload are validated left to right. The system resolves the first identifier in the path, then the next, then payload references, and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the **first** identifier that does not resolve to an existing resource — before any state, business, or shape rule is evaluated. A request to act on a direction under a non-existent default case therefore fails on the case lookup, never reaching the direction logic.

### 2.10. Hierarchical Consistency and Cascade Reconciliation

State changes propagate across the aggregate hierarchy to keep derived facts truthful. An indenture entering `DEFAULTED` suspends its scheduled payment runs and holds its pending distributions; clearing the last active default reverses both. A tranche reaching a terminal state contributes to indenture satisfaction; when every tranche is terminal the indenture becomes `SATISFIED`. A covenant obligation's waiver or breach feeds the indenture's `covenant_posture`. A trustee succession voids the indenture's draft fee invoices. Each cascade step mutates the affected resources, refreshing `updated_at` and incrementing `version` on each. Derived fields — `outstanding_principal_cents`, `covenant_posture`, `active_default_count`, `total_unpaid_cents`, `total_received_cents`, `eligible_principal_cents`, `supporting_principal_cents`, `consenting_principal_cents` — are never written by clients; they are recomputed by the server at the moments §3 specifies, and the reconciliation invariants of §3.2 and §3.4 hold at every observable instant.

## 3. Business Logic & Workflows

### 3.1. Drafting and Activating the Indenture

A corporate trust engagement begins when a `PlatformAdmin` creates an **Indenture** with its `name`, the opaque `issuer_ref` identifying the issuer (this value later anchors issuer ownership checks against `X-User-ID`), the `governing_law` label, the `initial_trustee_ref` naming the trustee appointed at activation, and the three fee parameters: `annual_admin_fee_cents`, `extraordinary_hourly_rate_cents`, and `default_hourly_rate_cents`. A new indenture is `DRAFT`, with `outstanding_principal_cents` initialized to zero, `covenant_posture` initialized to `CURRENT`, and `active_default_count` initialized to zero. From `DRAFT` an indenture may move only to `ACTIVE`, and activation — again a `PlatformAdmin` action — requires that at least one tranche already exists for the indenture; activating a tranche-less indenture is rejected with `ERR_INVALID_STATE`. Activation copies `initial_trustee_ref` into `current_trustee_ref` and increments the indenture's `version` by one.

A `PlatformAdmin` creates a **Tranche** against an indenture in `DRAFT` or `ACTIVE` status, supplying `indenture_id`, a `series_code` that must be unique within the indenture (a duplicate is rejected with `ERR_DUPLICATE_CONSTRAINT`), the `original_principal_cents` issued, the annual coupon `interest_rate_bps` in basis points, the `day_count_convention` — one of `ACT_360`, `ACT_365`, or `THIRTY_360` — the `payment_frequency` (`QUARTERLY`, `SEMI_ANNUAL`, or `ANNUAL`), the `maturity_date`, and optionally `notice_period_days`, which defaults to 30 when omitted and later governs redemption notice. A tranche is created `ACTIVE` with `outstanding_principal_cents` equal to its `original_principal_cents`, and its creation recomputes the parent indenture's `outstanding_principal_cents`, which is always the sum of the outstanding principal of its tranches. Tranche `status` thereafter moves among `ACTIVE`, `REDEEMED`, `MATURED`, and `ACCELERATED` only through the payment and default workflows of §3.4 and §3.5.

### 3.2. Holder Registration and Position Keeping

Before any distribution can flow, the trustee registers the holder base. A `PlatformAdmin` creates a **NoteholderAccount** with a globally unique `holder_ref` (any collision, across the whole system, is rejected with `ERR_DUPLICATE_CONSTRAINT`), the registered `legal_name`, and the notice `contact_email`. New accounts are `ACTIVE` with `total_unpaid_cents` and `total_received_cents` both zero; these two totals are derived ledgers maintained by the distribution workflows and are never written directly.

A `PlatformAdmin` then registers a **Position** by supplying `tranche_id`, `noteholder_account_id`, and `original_principal_cents`. Registration is capped by tranche size: the sum of `original_principal_cents` across all positions of a tranche must not exceed the tranche's `original_principal_cents`, and a registration that would breach the cap is rejected with `ERR_PRINCIPAL_EXCEEDS_POSITION` (HTTP 422). A new position starts `ACTIVE` with `principal_amount_cents` equal to its `original_principal_cents`, and its `principal_history` — an append-only series of snapshots, each pairing an `effective_from` instant with a `principal_cents` value — is seeded with a single entry at creation. Every executed redemption that reduces a position appends another entry, so the history always supports as-of lookups for record-date tabulation. A position whose `principal_amount_cents` reaches zero becomes `REDEEMED`.

One invariant governs all of §3.2 and §3.4, the **principal conservation rule**: for every tranche, `outstanding_principal_cents` always equals `original_principal_cents` minus the sum of principal reductions applied by executed, non-reversed redemption runs, and always equals the sum of `principal_amount_cents` over that tranche's `ACTIVE` positions; and the indenture's `outstanding_principal_cents` always equals the sum of its tranches' outstanding principal. Executing a redemption and then reversing that same run must leave all three quantities bit-identical to their pre-execution values.

### 3.3. The Covenant Calendar and Certificate Review Cycle

A `TrustOfficer` builds the indenture's obligation calendar by creating **CovenantObligation** rows. Each obligation carries `indenture_id`, a `covenant_type` of `FINANCIAL_REPORT`, `INSURANCE_CERT`, `DEBT_SERVICE_COVERAGE`, `LEVERAGE_RATIO`, or `TAX_COMPLIANCE`, a `frequency` of `QUARTERLY`, `SEMI_ANNUAL`, or `ANNUAL`, a `period_anchor_date` that seeds `next_due_date`, and an optional `grace_period_days` defaulting to 10. Ratio covenants — `DEBT_SERVICE_COVERAGE` and `LEVERAGE_RATIO` — require a `threshold_value`; whenever `threshold_value` is present, `threshold_direction` (`MIN` when the metric must be at least the threshold, `MAX` when it must not exceed it) and `measurement_basis` (`TTM` or `QUARTERLY_ANNUALIZED`, selecting which certificate metric is compared) are required as well. Obligations are created `OPEN`, and their creation recomputes the indenture's `covenant_posture`.

The issuer evidences compliance by submitting a **CovenantCertificate** naming `covenant_obligation_id`, the reporting `period_end_date`, and a `document_ref`; when the obligation carries a `threshold_value`, both `metric_value` (the period metric on a quarterly-annualized basis) and `ttm_metric_value` (the trailing-twelve-months metric) are required. Submission stamps `submitted_at` from the logical clock and computes `is_late`, which is true exactly when the submission date falls after the obligation's `next_due_date` as of that moment. The certificate is `SUBMITTED` and awaits review.

Review is a `TrustOfficer` action carrying a `decision` of accept or reject, with an optional `rejection_reason`. Acceptance of a certificate on a ratio obligation first runs the ratio check: the metric compared is `ttm_metric_value` when the obligation's `measurement_basis` is `TTM` and `metric_value` when it is `QUARTERLY_ANNUALIZED`; under direction `MIN` the metric must be at least `threshold_value`, under `MAX` it must be at most `threshold_value`, and equality passes in both directions. A failing metric rejects the acceptance with `ERR_COVENANT_RATIO_FAILED` (HTTP 422), and the same submitted financials can legitimately pass on one basis and fail on the other. On acceptance the certificate becomes `ACCEPTED`, `reviewed_by_user_id` records the reviewing officer, and the obligation rolls forward: it remains (or returns to) `OPEN` and its `next_due_date` advances by one `frequency` interval — the period outcome is observable on the certificate and on the advanced due date, because the obligation machine is cyclic. On rejection the certificate becomes `REJECTED`, the obligation's status is unchanged, and the issuer may submit a replacement.

The clock sweep drives the delinquency ladder. When the logical clock's date passes an `OPEN` obligation's `next_due_date` with no `ACCEPTED` certificate for the current period, the obligation becomes `LATE` and the indenture's `covenant_posture` is recomputed. When the clock's date passes `next_due_date` by more than `grace_period_days`, the obligation becomes `BREACHED`, the posture is recomputed again, and a `DefaultCase` is auto-created with `default_type` `COVENANT_BREACH`, `source_ref` pointing at the obligation, status `ALLEGED`, and a `cure_deadline` thirty days out from the sweep. The posture itself is derived: `BREACH` when any obligation of the indenture is `BREACHED`, else `GRACE` when any is `LATE`, else `CURRENT`. Accepting a late certificate returns a `LATE` obligation to `OPEN` with the standard roll-forward; accepting a certificate while `BREACHED` rolls forward identically and additionally cures the linked `ALLEGED` default case (the one whose `source_ref` is this obligation), which becomes `CURED` — and if that case was the indenture's last active default, the indenture resumes `ACTIVE` through the standard resume cascade of §3.5. Obligations in `OPEN`, `LATE`, or `BREACHED` may alternatively reach the terminal `WAIVED` state through a passed consent solicitation (§3.6); the waiver cascade also flips any linked `ALLEGED` default case to `WAIVED`.

### 3.4. Payment Agency: Scheduling, Funding, Execution, Settlement, and Reversal

The payment-agent function centers on the **PaymentRun**, which carries two parallel state dimensions on one entity: `funding_status` moves `UNFUNDED` → `PARTIALLY_FUNDED` → `FUNDED`, while `distribution_status` moves `SCHEDULED` → `DISTRIBUTED`, with `SUSPENDED` and `REVERSED` as the suspension and compensation branches. A run is created `UNFUNDED` and `SCHEDULED`, and its terminal combined state is `DISTRIBUTED` unless reversed.

A `TrustOfficer` schedules a run on an `ACTIVE` tranche — any other tranche state is rejected with `ERR_INVALID_STATE` — by naming `tranche_id`, `payment_type`, and `scheduled_payment_date`. For `payment_type` `INTEREST`, `period_start_date` and `period_end_date` are required and define a half-open accrual window that includes the start date and excludes the end date; the windows of a tranche's `INTEREST` runs must not overlap any other non-`REVERSED` run's window, though windows that merely touch at a boundary date are permitted, and a violating schedule is rejected with `ERR_PERIOD_OVERLAP`. For the redemption types `SINKING_FUND_REDEMPTION`, `FULL_REDEMPTION`, and `FINAL_MATURITY`, `target_amount_cents` is required, the run's `gross_amount_cents` equals `target_amount_cents` from creation, and `notice_sent_at` is stamped from the logical clock to record that holder notice was dispatched at creation. Redemption notice is enforced at scheduling: the scheduled payment date must fall at least the tranche's `notice_period_days` after the creation date, and a shorter notice is rejected with `ERR_NOTICE_PERIOD_SHORT` (HTTP 422). For `INTEREST` runs the `gross_amount_cents` is provisionally computed at creation and authoritatively recomputed at execution from the then-current positions, because redemptions between scheduling and execution may shrink the position set.

The issuer funds a run through deposits of `amount_cents`, which must be positive, and only while the run's `distribution_status` is `SCHEDULED`. Each deposit adds to `funded_amount_cents`; the first deposit that leaves a shortfall moves `funding_status` to `PARTIALLY_FUNDED`, and once the cumulative funded amount reaches or exceeds `gross_amount_cents` — exact equality is sufficient — the run is `FUNDED`.

Execution, a `TrustOfficer` action, is gated by three checks: the run must be `FUNDED` (a shortfall is rejected with `ERR_FUNDING_SHORTFALL`, equality executes), the indenture must be `ACTIVE` (otherwise `ERR_INDENTURE_NOT_ACTIVE`), and the tranche must be `ACTIVE` (otherwise `ERR_INVALID_STATE`); a run whose distribution status is `SUSPENDED` also refuses execution under the state rules. On execution `executed_at` is stamped from the logical clock and the run creates one **DistributionRecord**, status `PENDING`, per `ACTIVE` position of the tranche — including records whose allocation computes to zero cents. For `INTEREST` runs, each position's allocation is its accrued interest: the day count is the number of calendar days in the half-open accrual window, converted to a year fraction by dividing by 360 under `ACT_360` or by 365 under `ACT_365` — so identical inputs accrue more under `ACT_360` than under `ACT_365` — while under `THIRTY_360` the day count is 360 times the year difference plus 30 times the month difference plus the difference of the day-of-month components each capped at 30, over a 360-day year, ignoring actual month lengths. Each position's interest is its current `principal_amount_cents` times the tranche's `interest_rate_bps` divided by ten thousand, times the year fraction, rounded half-up to a whole cent **per position before any summation**, and the run's `gross_amount_cents` is the sum of those per-position amounts. For redemption runs the allocation is pro rata: each eligible position's raw share is the run's `gross_amount_cents` scaled by its `principal_amount_cents` over the total eligible principal; every raw share is floored to a whole cent first, and the remainder — the gross minus the sum of floored shares — is then distributed one cent at a time to positions in descending order of fractional part, with ties broken by creation time ascending and then by `original_principal_cents` descending, never by identifier. Redemption execution then reduces each position's `principal_amount_cents` by its allocated share, appends the new value to `principal_history`, moves zeroed positions to `REDEEMED`, recomputes the tranche's `outstanding_principal_cents`, and recomputes the indenture's `outstanding_principal_cents`. A `FULL_REDEMPTION` or `FINAL_MATURITY` execution that leaves the tranche's outstanding principal at zero moves the tranche to `REDEEMED` or `MATURED` respectively, with all of its positions `REDEEMED`; and when every tranche of the indenture has reached a terminal state (`REDEEMED` or `MATURED`), the indenture itself becomes `SATISFIED`, its terminal state.

Holder cash totals move only at settlement. A clock sweep at or after a run's `scheduled_payment_date` moves that run's `PENDING` records to `PAID`, stamps `paid_at` from the logical clock, and adds each `allocated_cents` to the holder's `total_received_cents` — but the sweep skips settlement entirely while the indenture is `DEFAULTED` or `ACCELERATED`. Two compensation paths exist. A `TrustOfficer` may mark an individual `PAID` record `RETURNED` — misdirected funds clawed back to the trustee — while the run remains `DISTRIBUTED`, decrementing the holder's `total_received_cents` by the record's `allocated_cents`. A `TrustManager` may reverse an entire `DISTRIBUTED` run, provided none of its records is already `RETURNED` (otherwise `ERR_INVALID_STATE`): the run's `distribution_status` becomes `REVERSED`, every record in `PENDING`, `HELD`, or `PAID` becomes `RETURNED`, redemption principal reductions are undone with `principal_amount_cents` restored and the restored value appended to `principal_history`, positions the run had redeemed return to `ACTIVE`, the tranche's `outstanding_principal_cents` is restored and a tranche this run had moved to `REDEEMED` or `MATURED` returns to `ACTIVE`, holder `total_received_cents` is decremented by returned allocations and `total_unpaid_cents` decremented for records returning from `HELD`, and `funding_status` remains `FUNDED` because the funds stay on deposit.

### 3.5. Events of Default and Noteholder Direction

When an event of default is alleged, a `TrustOfficer` declares a **DefaultCase** with `indenture_id`, a `default_type` of `PAYMENT`, `COVENANT_BREACH`, `CROSS_DEFAULT`, `BANKRUPTCY`, or `SINKING_FUND_MISS`, a `cure_deadline`, and an optional `source_ref` identifying an originating covenant obligation or payment run. Declaration stamps `declared_at` from the logical clock, records the officer as `declared_by_user_id`, sets the case `ALLEGED`, and recomputes the indenture's `active_default_count` — the count of its cases in `CONFIRMED` or `ACCELERATED`.

Confirmation is deliberately a second pair of hands. A `TrustManager` confirms an `ALLEGED` case, and the confirming `X-User-ID` must differ from `declared_by_user_id`; the same individual attempting both halves is rejected with `ERR_SEGREGATION_OF_DUTIES`. Confirmation records `confirmed_by_user_id`, moves the case to `CONFIRMED`, and fires the full default cascade: the indenture moves `ACTIVE` → `DEFAULTED`, every payment run of every tranche with `distribution_status` `SCHEDULED` becomes `SUSPENDED`, every `PENDING` distribution record under a `DISTRIBUTED` run of the indenture becomes `HELD` with its `allocated_cents` added to the holder's `total_unpaid_cents`, and each affected account's unpaid total is recomputed. A `TrustManager` may cure a `CONFIRMED` case while the logical clock reads at or before `cure_deadline` — a cure at the exact deadline instant is valid, and a cure attempted later is rejected with `ERR_CURE_DEADLINE_PASSED`. Curing moves the case to `CURED` and recomputes `active_default_count`; when the count reaches zero the indenture resumes `DEFAULTED` → `ACTIVE` through the resume cascade — suspended runs return to `SCHEDULED`, held records return to `PENDING` with `total_unpaid_cents` decremented accordingly, and settled totals update at the next settlement sweep.

Holders direct the trustee through a **NoteholderDirection**. A `TrustOfficer` opens a direction on a default case that is `CONFIRMED` or `ACCELERATED` (any other case state is inadmissible and rejected with `ERR_INVALID_STATE`), supplying `default_case_id`, an `instruction_type` of `ACCELERATE`, `RESCIND_ACCELERATION`, or `WAIVE_DEFAULT`, an `expires_at` circulation deadline, and the OCC field `expected_default_case_version` per §2.7. Opening a direction supersedes any `CIRCULATING` sibling on the same case (which becomes `SUPERSEDED`), increments the case's `version` by one, and starts the direction `CIRCULATING` with `eligible_principal_cents` — the sum of `principal_amount_cents` over `ACTIVE` positions of the indenture's tranches in `ACTIVE` or `ACCELERATED` status, so acceleration does not extinguish voting principal — and `supporting_principal_cents`, the sum of `endorsed_principal_cents` over `ACTIVE` endorsements. Both aggregates are recomputed on every endorsement and every withdrawal. The `threshold_rule` on the direction restates the governing test in words: for `ACCELERATE` and `WAIVE_DEFAULT` the direction becomes `EFFECTIVE` when supporting principal reaches at least one quarter of eligible principal, the boundary inclusive — evaluated as supporting multiplied by four being at least the eligible figure — while for `RESCIND_ACCELERATION` the test is strict, requiring more than one half — supporting multiplied by two exceeding the eligible figure; both tests use integer cross-multiplication only. A withdrawal that drops support below the threshold flips an `EFFECTIVE` direction back to `CIRCULATING`.

A `Noteholder` endorses a circulating direction by naming its `noteholder_account_id`, which must equal the caller's `X-User-ID`. Endorsement requires an eligible position: the holder's aggregate principal across `ACTIVE` positions of the indenture must exceed zero, else `ERR_NO_ELIGIBLE_POSITION`; at most one `ACTIVE` endorsement exists per direction and account, else `ERR_DUPLICATE_CONSTRAINT`; and the direction must be `CIRCULATING` or `EFFECTIVE` with the logical clock strictly before `expires_at`, else `ERR_DIRECTION_LAPSED`. A successful endorsement is `ACTIVE` and snapshots the holder's aggregate `ACTIVE` principal across the indenture into `endorsed_principal_cents` at endorsement time. The same holder may later withdraw, again under ownership and only while the direction is `CIRCULATING` or `EFFECTIVE` (otherwise `ERR_INVALID_STATE`); withdrawal moves the endorsement to `WITHDRAWN` and recomputes support, collapsing the direction to `CIRCULATING` if the threshold is lost. Directions whose circulation deadline passes without execution are swept to `LAPSED`.

Execution belongs to the `TrustManager` and requires the direction to be `EFFECTIVE` at that moment — executing one that is not is rejected with `ERR_THRESHOLD_NOT_MET`. An executed direction becomes `EXECUTED` and applies its instruction: `ACCELERATE` moves the default case `CONFIRMED` → `ACCELERATED`, the indenture `DEFAULTED` → `ACCELERATED`, and every `ACTIVE` tranche to `ACCELERATED`; `WAIVE_DEFAULT` moves the case `CONFIRMED` → `WAIVED`, recomputes `active_default_count`, and fires the resume cascade when the last active default clears; `RESCIND_ACCELERATION` moves the case `ACCELERATED` → `CONFIRMED`, the indenture `ACCELERATED` → `DEFAULTED`, and every `ACCELERATED` tranche back to `ACTIVE`.

### 3.6. Consent Solicitations

An issuer seeking to amend terms or waive a covenant opens a **ConsentSolicitation**, acting on an indenture it owns. Creation supplies `indenture_id`, a `subject_type` of `AMEND_TERMS` or `WAIVE_COVENANT`, the required consent share `consent_threshold_bps` in basis points of eligible principal (5000 denotes fifty percent), the `tabulation_basis` of `RECORD_DATE` or `CURRENT_OUTSTANDING`, the `record_date`, and the `expiry_date`. A `WAIVE_COVENANT` solicitation requires `target_obligation_id` referencing a covenant obligation **of the same indenture** — a missing or cross-indenture target is rejected with `ERR_TARGET_OBLIGATION_MISMATCH`. An `AMEND_TERMS` solicitation requires an `amendment_payload`; the currently supported key is `annual_admin_fee_cents`, applied to the indenture when the solicitation passes. Solicitation windows are the **closed** interval from `record_date` through `expiry_date`, and the windows of one indenture's solicitations must not overlap another solicitation in `DRAFT` or `OPEN` — a shared boundary date already counts as a collision, and an overlapping creation is rejected with `ERR_SOLICITATION_WINDOW_OVERLAP`. New solicitations are `DRAFT`.

A `TrustOfficer` opens a `DRAFT` solicitation for balloting, which requires the logical clock's date to be on or before `expiry_date`; opening after expiry is rejected with `ERR_SOLICITATION_EXPIRED`. While `OPEN`, a `Noteholder` casts a ballot naming `noteholder_account_id` (again its own — ownership applies) and a `vote` of `CONSENT` or `WITHHOLD`. At most one ballot exists per solicitation and account (a repeat is `ERR_DUPLICATE_CONSTRAINT`), balloting after `expiry_date` is rejected with `ERR_SOLICITATION_EXPIRED`, and the caster must be a holder of record: under `CURRENT_OUTSTANDING` the holder's aggregate `ACTIVE` position principal must exceed zero, and under `RECORD_DATE` the holder's principal as of the record date — resolved from `principal_history` — must exceed zero, else `ERR_NO_ELIGIBLE_POSITION`. Each accepted ballot appends to the solicitation's `ballots` array an entry recording the account, the `vote`, the `principal_voted_cents` weight computed per the tabulation basis, and the `cast_at` instant, and the consenting tally is maintained as ballots arrive.

Closing, again a `TrustOfficer` action, tabulates and resolves the solicitation with three mutually exclusive outcomes given equal treatment. When the clock's date is on or before `expiry_date`, eligible principal is the sum of `principal_amount_cents` over `ACTIVE` positions of the indenture's tranches in `ACTIVE` or `ACCELERATED` status; `consenting_principal_cents` is the summed weight of `CONSENT` ballots, weighted per the tabulation basis — under `RECORD_DATE`, each ballot's weight is frozen at the holder's aggregate principal as of the end of `record_date` (the latest `principal_history` entry per position whose `effective_from` is at or before 23:59:59.999 UTC on the record date governs, and a position whose first history entry postdates the record date contributes zero), so redemptions executed between the record date and close do not change weights, while under `CURRENT_OUTSTANDING` weights are recomputed at close, so interim redemptions reduce them and identical ballots yield a smaller tally. The solicitation becomes `PASSED` when the consenting weight multiplied by ten thousand is at least `consent_threshold_bps` multiplied by the eligible principal — integer cross-multiplication with no floating-point division — and `FAILED` otherwise, with zero ballots failing any positive threshold because the consenting weight is zero. When the clock's date is past `expiry_date` at close, the solicitation becomes `EXPIRED` regardless of the tally — expiry wins over tabulation. A passed solicitation applies its subject: `WAIVE_COVENANT` moves the target obligation to `WAIVED`, flips any linked `ALLEGED` default case to `WAIVED`, and recomputes the indenture's `covenant_posture`; `AMEND_TERMS` applies `amendment_payload.annual_admin_fee_cents` to the indenture, incrementing the indenture's `version`. An issuer may revoke its own solicitation from `DRAFT` or `OPEN`, moving it to `REVOKED`.

### 3.7. Collateral Release and Substitution

A `TrustOfficer` registers each **CollateralItem** with `indenture_id`, a `description`, a `collateral_type` of `REAL_ESTATE`, `EQUIPMENT`, `SECURITIES`, or `GUARANTEE`, the latest `appraised_value_cents`, and the appraisal `valuation_date`; items begin `PLEDGED`. An issuer that owns the indenture may then request a release or substitution by creating a **CollateralReleaseRequest** with `collateral_item_id`, a `request_type` of `RELEASE` or `SUBSTITUTION`, and the OCC field `expected_collateral_item_version` per §2.7. A `SUBSTITUTION` request additionally requires `substitute_description`, `substitute_collateral_type` (the same four-type enumeration), `substitute_appraised_value_cents`, and `substitute_valuation_date`; a substitution missing any of them is rejected with `ERR_SUBSTITUTE_REQUIRED` (HTTP 400). Valuation freshness is enforced both at request creation and at verification: the item's `valuation_date` — and, for substitutions, the substitute's `substitute_valuation_date` — must lie within 180 days of the acting date, and a valuation more than 180 days old is rejected with `ERR_VALUATION_STALE` (HTTP 422). Creating a request supersedes any `SUBMITTED` sibling on the same item (which becomes `SUPERSEDED`), increments the item's `version` by one, and starts the request `SUBMITTED`.

Verification, a `TrustOfficer` step, re-checks valuation freshness and computes `post_release_coverage_bps` under a pinned evaluation order, because the substitute's own haircut depends on coverage computed **without** the substitute and any other order is non-convergent. First, value every `PLEDGED` collateral item of the indenture excluding the item under request, each at its `appraised_value_cents` discounted by its type haircut — 2000 basis points for `REAL_ESTATE`, 3000 for `EQUIPMENT`, 500 for `SECURITIES`, and 4000 for `GUARANTEE` — and sum. Second, divide that coverage by the indenture's `outstanding_principal_cents`: when the ratio is at least 2.00 the substitute is valued at a 1000-basis-point haircut, otherwise at 2500 basis points. Third, the substitute contribution is its `substitute_appraised_value_cents` discounted by that haircut — zero for a plain `RELEASE`. Fourth, `post_release_coverage_bps` is the total post-release coverage multiplied by ten thousand and divided by the indenture's `outstanding_principal_cents`, rounded down to a whole basis point. Verification records `verified_by_user_id` and moves the request to `VERIFIED`.

The decision belongs to a `TrustManager` carrying a `decision` of approve or reject, and its checks run in a fixed order: segregation of duties first — the decider's `X-User-ID` must differ from `verified_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`; then the default lock — a decision is rejected with `ERR_DEFAULT_LOCK` while any default case of the indenture is `CONFIRMED` or `ACCELERATED`; then, for approval, the coverage floor — `post_release_coverage_bps` must be at least 12500 (that is, coverage of at least 125 percent of outstanding principal), with equality approving and a shortfall rejected as `ERR_COVERAGE_BELOW_MINIMUM` (HTTP 422). A decided request becomes `APPROVED` or `REJECTED` with `decided_by_user_id` recorded. Effecting an `APPROVED` request — a `TrustOfficer` action — requires the collateral item still `PLEDGED` (otherwise `ERR_INVALID_STATE`); the request becomes `EFFECTED`, and the item moves to `RELEASED` for a release or to `SUBSTITUTED` for a substitution, in which case a new `CollateralItem` is auto-created in `PLEDGED` status from the `substitute_*` fields with its `substituted_from_item_id` pointing back at the original item. Indenture-level collateral totals recompute implicitly through the status filter, and the collateral listing doubles as the discovery channel for substitution-created items.

### 3.8. Trustee Compensation and Extraordinary Services

Trustee compensation runs through the **FeeInvoice**. A `TrustOfficer` drafts an invoice with `indenture_id`, an `invoice_type` of `ANNUAL_ADMIN` or `EXTRAORDINARY_SERVICE`, the `service_period_start` and `service_period_end` dates, a narrative `description`, and — required exactly when the type is `EXTRAORDINARY_SERVICE` — the `extraordinary_hours` worked. The `amount_cents` of an `ANNUAL_ADMIN` invoice is simply the indenture's `annual_admin_fee_cents`. Extraordinary billing requires an extraordinary basis: at least one default case of the indenture must have reached `CONFIRMED`, `CURED`, `WAIVED`, or `ACCELERATED` with its `declared_at` at or before `service_period_end`, else drafting is rejected with `ERR_NO_EXTRAORDINARY_BASIS` (HTTP 422). The extraordinary amount uses the indenture's `default_hourly_rate_cents` while the indenture is `DEFAULTED` or `ACCELERATED` and its `extraordinary_hourly_rate_cents` otherwise; the first ten hours are billed at the applicable rate and rounded half-up to whole cents, the hours beyond ten are billed at one and a half times the rate and likewise rounded half-up, and the invoice amount is the sum of the two tier charges capped at four times the indenture's `annual_admin_fee_cents`. Drafting records `drafted_by_user_id` and leaves the invoice `DRAFT`.

Issuance is the segregated second step: a `TrustManager` issues a `DRAFT` — or, later, an `AMENDED` — invoice, and the issuer's `X-User-ID` must differ from `drafted_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`; issuance records `issued_by_user_id` and moves the invoice to `ISSUED`. The owning issuer then either pays the `ISSUED` invoice, moving it to the terminal `PAID`, or disputes it, moving it to `DISPUTED`. A `TrustOfficer` amends a `DISPUTED` invoice, replacing `extraordinary_hours` and/or `description` and recomputing `amount_cents` under the same tiered rule — and because the rate basis is read from the indenture's status at computation time, an amendment after a default event can flip the rate even for identical hours. The amended invoice returns to `ISSUED` through the same segregated issuance step. Separately, a trustee succession voids drafts: when a trustee appointment on the indenture becomes `EFFECTIVE`, every invoice of that indenture still `DRAFT` moves to `VOID`.

### 3.9. Successor Trustee Appointments

Trustee succession is a `PlatformAdmin` workflow built around the **TrusteeAppointment**. Creating an appointment supplies `indenture_id`, the `incoming_trustee_ref` naming the successor, a `reason` of `RESIGNATION`, `REMOVAL`, or `CONSOLIDATION`, the `proposed_effective_date`, and the OCC field `expected_indenture_version` per §2.7. Creation snapshots the indenture's `current_trustee_ref` into `outgoing_trustee_ref`, supersedes any in-flight appointment on the same indenture — both `PROPOSED` and `ACCEPTED` siblings become `SUPERSEDED` — increments the indenture's `version` by one, and starts the appointment `PROPOSED`. Acceptance records the successor's acceptance and moves the appointment to `ACCEPTED`. Effecting the transfer requires the logical clock's date to be on or after `proposed_effective_date`; an earlier attempt is rejected with `ERR_NOT_YET_EFFECTIVE`. On effectiveness the appointment becomes `EFFECTIVE`, the indenture's `current_trustee_ref` is swapped to the `incoming_trustee_ref`, the indenture's `version` increments again, and every `DRAFT` fee invoice of the indenture is voided per §3.8. A `PlatformAdmin` may rescind an appointment from either `PROPOSED` or `ACCEPTED`, moving it to `RESCINDED`; `EFFECTIVE`, `RESCINDED`, and `SUPERSEDED` are terminal.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource or drive a state transition return `200 OK`. All endpoints are subject to the validation order of §2.8 and the envelope of §2.2; list endpoints paginate per §2.3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock and trigger the system sweep | PlatformAdmin |
| POST | `/indentures` | Create an indenture in `DRAFT` | PlatformAdmin |
| GET | `/indentures` | List indentures | All roles |
| GET | `/indentures/{id}` | Get one indenture | All roles |
| POST | `/indentures/{id}/activate` | Activate a `DRAFT` indenture (requires at least one tranche) | PlatformAdmin |
| POST | `/tranches` | Create a tranche on a `DRAFT` or `ACTIVE` indenture | PlatformAdmin |
| GET | `/tranches` | List tranches, filterable by `indenture_id` and `status` | All roles |
| GET | `/tranches/{id}` | Get one tranche | All roles |
| POST | `/noteholder-accounts` | Register a noteholder account | PlatformAdmin |
| GET | `/noteholder-accounts` | List noteholder accounts | All roles |
| GET | `/noteholder-accounts/{id}` | Get one noteholder account | All roles |
| POST | `/positions` | Register a position within the tranche's principal cap | PlatformAdmin |
| GET | `/positions` | List positions, filterable by `tranche_id`, `noteholder_account_id`, and `status` | All roles |
| GET | `/positions/{id}` | Get one position | All roles |
| POST | `/covenant-obligations` | Create a covenant obligation on the indenture calendar | TrustOfficer |
| GET | `/covenant-obligations` | List covenant obligations, filterable by `indenture_id` and `status` | All roles |
| GET | `/covenant-obligations/{id}` | Get one covenant obligation | All roles |
| POST | `/covenant-certificates` | Issuer submits a compliance certificate for an obligation | Issuer |
| GET | `/covenant-certificates` | List certificates, filterable by `covenant_obligation_id` and `status` | All roles |
| GET | `/covenant-certificates/{id}` | Get one certificate | All roles |
| POST | `/covenant-certificates/{id}/review` | Accept or reject a `SUBMITTED` certificate | TrustOfficer |
| POST | `/payment-runs` | Schedule a payment run on an `ACTIVE` tranche | TrustOfficer |
| GET | `/payment-runs` | List payment runs, filterable by `tranche_id`, `funding_status`, and `distribution_status` | All roles |
| GET | `/payment-runs/{id}` | Get one payment run | All roles |
| POST | `/payment-runs/{id}/fund` | Issuer deposits funds against a run | Issuer |
| POST | `/payment-runs/{id}/execute` | Execute a `FUNDED` run and create per-position distribution records | TrustOfficer |
| POST | `/payment-runs/{id}/reverse` | Compensating reversal of a `DISTRIBUTED` run | TrustManager |
| GET | `/distribution-records` | List distribution records, filterable by `payment_run_id`, `position_id`, and `status` | All roles |
| GET | `/distribution-records/{id}` | Get one distribution record | All roles |
| POST | `/distribution-records/{id}/return` | Mark a `PAID` record `RETURNED` | TrustOfficer |
| POST | `/default-cases` | Declare an event of default (`ALLEGED`) | TrustOfficer |
| GET | `/default-cases` | List default cases, filterable by `indenture_id` and `status` | All roles |
| GET | `/default-cases/{id}` | Get one default case | All roles |
| POST | `/default-cases/{id}/confirm` | Confirm an `ALLEGED` default, triggering the default cascade | TrustManager |
| POST | `/default-cases/{id}/cure` | Cure a `CONFIRMED` default at or before its deadline | TrustManager |
| POST | `/directions` | Open a noteholder direction on a `CONFIRMED`/`ACCELERATED` case | TrustOfficer |
| GET | `/directions` | List directions, filterable by `default_case_id` and `status` | All roles |
| GET | `/directions/{id}` | Get one direction | All roles |
| POST | `/directions/{id}/endorsements` | Noteholder endorses a circulating direction | Noteholder |
| GET | `/direction-endorsements` | List endorsements, filterable by `direction_id`, `noteholder_account_id`, and `status` | All roles |
| GET | `/direction-endorsements/{id}` | Get one endorsement | All roles |
| POST | `/direction-endorsements/{id}/withdraw` | Endorsing holder withdraws support | Noteholder |
| POST | `/directions/{id}/execute` | Execute an `EFFECTIVE` direction (accelerate / waive / rescind) | TrustManager |
| POST | `/consent-solicitations` | Issuer opens a consent solicitation draft | Issuer |
| GET | `/consent-solicitations` | List solicitations, filterable by `indenture_id` and `status` | All roles |
| GET | `/consent-solicitations/{id}` | Get one solicitation | All roles |
| POST | `/consent-solicitations/{id}/open` | Open a `DRAFT` solicitation for balloting | TrustOfficer |
| POST | `/consent-solicitations/{id}/ballots` | Noteholder casts a ballot | Noteholder |
| POST | `/consent-solicitations/{id}/close` | Tabulate and close: `PASSED`, `FAILED`, or `EXPIRED` | TrustOfficer |
| POST | `/consent-solicitations/{id}/revoke` | Issuer revokes a `DRAFT` or `OPEN` solicitation | Issuer |
| POST | `/collateral-items` | Register pledged collateral | TrustOfficer |
| GET | `/collateral-items` | List collateral items, filterable by `indenture_id` and `status` | All roles |
| GET | `/collateral-items/{id}` | Get one collateral item | All roles |
| POST | `/collateral-release-requests` | Issuer requests a release or substitution | Issuer |
| GET | `/collateral-release-requests` | List release requests, filterable by `collateral_item_id` and `status` | All roles |
| GET | `/collateral-release-requests/{id}` | Get one release request | All roles |
| POST | `/collateral-release-requests/{id}/verify` | Verify a `SUBMITTED` request and compute post-release coverage | TrustOfficer |
| POST | `/collateral-release-requests/{id}/decide` | Approve or reject a `VERIFIED` request | TrustManager |
| POST | `/collateral-release-requests/{id}/effect` | Effect an `APPROVED` request | TrustOfficer |
| POST | `/fee-invoices` | Draft a fee invoice | TrustOfficer |
| GET | `/fee-invoices` | List fee invoices, filterable by `indenture_id`, `status`, and `invoice_type` | All roles |
| GET | `/fee-invoices/{id}` | Get one fee invoice | All roles |
| POST | `/fee-invoices/{id}/issue` | Issue a `DRAFT` or `AMENDED` invoice | TrustManager |
| POST | `/fee-invoices/{id}/pay` | Issuer pays an `ISSUED` invoice | Issuer |
| POST | `/fee-invoices/{id}/dispute` | Issuer disputes an `ISSUED` invoice | Issuer |
| POST | `/fee-invoices/{id}/amend` | Amend a `DISPUTED` invoice and recompute the amount | TrustOfficer |
| POST | `/trustee-appointments` | Propose a successor trustee | PlatformAdmin |
| GET | `/trustee-appointments` | List appointments, filterable by `indenture_id` and `status` | All roles |
| GET | `/trustee-appointments/{id}` | Get one appointment | All roles |
| POST | `/trustee-appointments/{id}/accept` | Record successor acceptance | PlatformAdmin |
| POST | `/trustee-appointments/{id}/effect` | Complete the trustee transfer on or after the proposed date | PlatformAdmin |
| POST | `/trustee-appointments/{id}/rescind` | Rescind a `PROPOSED` or `ACCEPTED` appointment | PlatformAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in §2 and §3 alongside the rules and workflows that raise them; this catalogue lists identifiers and statuses only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_SUBSTITUTE_REQUIRED` | 400 Bad Request |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_OWNERSHIP_VIOLATION` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_INDENTURE_NOT_ACTIVE` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 409 Conflict |
| `ERR_DEFAULT_LOCK` | 409 Conflict |
| `ERR_NO_EXTRAORDINARY_BASIS` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_CONSTRAINT` | 409 Conflict |
| `ERR_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_SOLICITATION_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_PRINCIPAL_EXCEEDS_POSITION` | 422 Unprocessable Entity |
| `ERR_COVERAGE_BELOW_MINIMUM` | 422 Unprocessable Entity |
| `ERR_NOTICE_PERIOD_SHORT` | 422 Unprocessable Entity |
| `ERR_CURE_DEADLINE_PASSED` | 409 Conflict |
| `ERR_DIRECTION_LAPSED` | 409 Conflict |
| `ERR_SOLICITATION_EXPIRED` | 409 Conflict |
| `ERR_VALUATION_STALE` | 422 Unprocessable Entity |
| `ERR_NOT_YET_EFFECTIVE` | 409 Conflict |
| `ERR_FUNDING_SHORTFALL` | 422 Unprocessable Entity |
| `ERR_COVENANT_RATIO_FAILED` | 422 Unprocessable Entity |
| `ERR_TARGET_OBLIGATION_MISMATCH` | 422 Unprocessable Entity |
| `ERR_NO_ELIGIBLE_POSITION` | 422 Unprocessable Entity |
| `ERR_THRESHOLD_NOT_MET` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
