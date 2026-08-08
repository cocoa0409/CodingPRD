# Cable-Broadband Franchise & PEG API — Product Requirements Document

## 1. Introduction

Local franchising authorities — cities and counties — grant cable and broadband operators the privilege of occupying public right-of-way in exchange for a franchise fee, build-out obligations, PEG/I-Net capital support, and responsiveness to customer complaints. Administering these grants by hand is error-prone: fee calculations depend on gross-revenue categories that are periodically audited and re-stated, build-out density must be certified against deadlines, right-of-way work must be de-conflicted in time and space, and transfers or renewals of the grant have to be adjudicated within statutory windows or else be deemed approved by default.

This API is the authoritative system of record for that lifecycle. It models each franchise as a grant carrying two independent status axes — a **lifecycle** axis (draft, active, renewal, transfer, revocation, expiry) and a **compliance** axis (compliant, in-violation, cured) — and it ties together the peer records that hang off a franchise: right-of-way segments and permits, build-out milestones, revenue reports, audits and underpayment assessments, customer complaints, PEG contributions, and transfer/renewal applications. The system enforces the fiscal arithmetic exactly, cascades compliance findings across related records, and applies segregation-of-duties and optimistic-concurrency guarantees so that two authorities, or an authority and an operator, cannot corrupt each other's view of the record.

Because many rules in this domain are time-gated (SLA breaches, deemed-approval windows, milestone deadlines, interest accrual), the server maintains a **logical clock** rather than reading wall-clock time. All temporal comparisons in this document refer to that logical clock.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the principal's role. If `X-User-Role` is missing or is not one of the three known roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the header is present and valid but the role is not permitted to invoke the requested operation (per the authorization matrix in Section 4), the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

There are exactly three roles:

- **`FranchiseAuthority`** — local franchising-authority staff. They grant and activate franchises, revoke and cure them, register right-of-way segments, decide permits, set build-out milestones, accept revenue reports, open and finalize audits, waive assessments, escalate complaints, void PEG contributions, decide transfer/renewal applications, and drive the logical clock. When `X-User-Role` is `FranchiseAuthority`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where a transition captures the acting user — for example as `decided_by_user_id` on a permit or application, `finalized_by_user_id` on an audit, or `issued_by_user_id` on an assessment — but it never compares that identifier to any entity's `id`.
- **`Operator`** — the cable/broadband company that holds a franchise. When `X-User-Role` is `Operator`, `X-User-ID` is the `id` of the acting `Franchise`; ownership checks on any franchise-scoped resource compare the resource's `franchise_id` to `X-User-ID`. An Operator write against a resource whose `franchise_id` does not equal the caller's `X-User-ID` is rejected with `ERR_NOT_FRANCHISE_OWNER` (HTTP 403).
- **`Resident`** — a customer or member of the public who files and manages complaints. When `X-User-Role` is `Resident`, `X-User-ID` is an opaque identifier not tied to any persisted entity. The server records it as `complainant_id` when a complaint is filed but does not compare it to any entity's `id`; the one place it is re-examined is complaint reopening, where the caller's `X-User-ID` must equal the stored `complainant_id`.

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

List endpoints accept two query parameters, `limit` and `offset`. `limit` defaults to 10, has a minimum of 1, and a maximum of 100; `offset` defaults to 0 and has a minimum of 0. Out-of-range pagination values are clamped rather than rejected: a `limit` below 1 becomes 1 and above 100 becomes 100, a negative `offset` becomes 0, and a `limit` or `offset` that is not a parseable integer falls back to its default (10 and 0 respectively). Results are always returned sorted by `created_at` in ascending order. The `meta` block of a list response carries `limit`, `offset`, `total_count` (the total number of records matching the query before pagination), and `has_more` (true when records remain beyond the current page).

### 2.4. Common Resource Properties and the Logical Clock

Every resource in this system carries a server-minted `id` (a UUID with no type prefix) and a `created_at` timestamp (ISO 8601 UTC, three fractional digits). Every entity in this system also carries `updated_at` (ISO 8601 UTC, three fractional digits) and an integer `version`. The `version` begins at 1 when the resource is created; every state-changing mutation of that resource increments its `version` by exactly 1 and refreshes `updated_at`. Reads never mutate `version`.

The logical clock starts at `2026-05-01T00:00:00Z`. Before any clock-setting call, every time-gated rule reads exactly that default instant — the server never falls back to wall-clock time. An authority may advance (or reset) the clock by supplying a `to_iso8601` instant; all subsequent SLA, deemed-approval, milestone-deadline, and interest computations use the clock's current value. Timestamps that the server stamps from the clock — `filed_at`, `escalated_at`, `submitted_at`, `finalized_at`, and `last_certified_at` — reflect the clock at the moment of the operation. The clock-setting endpoint returns an object whose `data` is `{ "current_utc": <the `to_iso8601` instant just applied, echoed verbatim> }`.

### 2.5. Optimistic Concurrency on Franchise Applications

Filing a transfer or renewal application is guarded by optimistic concurrency against the target franchise. The create request must carry `expected_franchise_version`, which must equal the franchise's current `version`. If another writer has advanced the franchise's `version` since the client last read it, the create is rejected with `ERR_STALE_VERSION` (HTTP 412). This is what prevents a client working from a stale view of the franchise from clobbering the supersede that an intervening application filing performed: a newly filed application legitimately withdraws any prior submitted application on the same franchise, and the version check ensures the client that files knew about the franchise's latest state. Only the application-filing operation takes `expected_franchise_version`; no other endpoint accepts a version field. Every successful application filing increments the target franchise's `version` by exactly 1 and refreshes its `updated_at` (independently of any lifecycle change the filing may also cause), so a subsequent filing that reuses the pre-filing version value is what trips `ERR_STALE_VERSION`.

### 2.6. Monetary Precision and Rounding

All money is represented as an integer number of cents. Wherever a rate or fraction is multiplied against a cents amount, the result is rounded **half up** to a whole cent. The franchise-fee computation rounds **per line item before summing** — each gross category is rounded to a whole cent on its own, and only then are the rounded line items added; the system never sums first and rounds once. Interest and penalty computations likewise round half up at each rounding step. Counts of homes and days are whole integers throughout.

### 2.7. The Dual-Axis Franchise Status Model

A `Franchise` carries two independent status axes that never share transitions. The **lifecycle axis** (`lifecycle_status`) takes one of `DRAFT`, `ACTIVE`, `RENEWAL_PENDING`, `RENEWED`, `TRANSFERRED`, `EXPIRED`, or `REVOKED`; the states `TRANSFERRED`, `EXPIRED`, and `REVOKED` are terminal and forbid any further lifecycle transition. The **compliance axis** (`compliance_status`) takes one of `COMPLIANT`, `IN_VIOLATION`, or `CURED`. A grant is created at `DRAFT`/`COMPLIANT`.

The two axes interact only through cascades. When an audit finding or a complaint-escalation threshold flips a franchise from `COMPLIANT` or `CURED` to `IN_VIOLATION`, that flip cascades: every application of that franchise currently in `SUBMITTED` is moved to `HELD`. When an authority cures the franchise (`IN_VIOLATION` → `CURED`), `unresolved_complaint_count` is reset to 0 and every application currently `HELD` is released back to `SUBMITTED`. Each such cascade bumps the `version` and refreshes `updated_at` of every entity it touches — the franchise itself and each application whose status it changes.

### 2.8. Validation Ordering and Error Precedence

When more than one rule could fail on a single request, checks are evaluated in a fixed priority order, and the first failure determines the response:

1. **Authentication** — `X-User-Role` present and a known role, else `ERR_UNAUTHENTICATED` (401).
2. **Request well-formedness** — on every write, required fields present, enum values legal, numeric types and ranges valid, else `ERR_INVALID_REQUEST` (400). Date/interval ordering is checked here too: a `period_end_date` earlier than `period_start_date`, a `window_end` at or before `window_start`, or a `term_end_date` at or before `term_start_date` yields `ERR_VALIDATION_PERIOD_INVALID` (400). Conditionally required application fields are also checked at this stage (see Section 3.8).
3. **Authorization** — the acting role is permitted to call this endpoint, else `ERR_UNAUTHORIZED` (403).
4. **Existence** — every path `id` and every body foreign key resolves to an existing resource, validated left-to-right, else `ERR_NOT_FOUND` (404).
5. **Ownership** — for Operator-authored writes on franchise-scoped resources, `X-User-ID` equals the target's `franchise_id`, else `ERR_NOT_FRANCHISE_OWNER` (403).
6. **Segregation of duties** — on assessment waiver, the caller is not the issuer, else `ERR_SEGREGATION_OF_DUTIES` (403).
7. **State** — the target is in a state from which the requested transition is defined, else `ERR_INVALID_STATE` (409).
8. **Domain preconditions** — the endpoint-specific business rules described in Section 3, in the priority order given there: franchise-active for permits (`ERR_FRANCHISE_NOT_ACTIVE`), SLA breach for escalation (`ERR_SLA_NOT_BREACHED`), compliance for application approval (`ERR_FRANCHISE_IN_VIOLATION`), milestones-met for renewal approval (`ERR_MILESTONES_NOT_MET`), permit-window overlap (`ERR_PERMIT_WINDOW_OVERLAP`), audit-period overlap (`ERR_AUDIT_PERIOD_OVERLAP`), payment amount (`ERR_PAYMENT_AMOUNT_MISMATCH`), and franchise version (`ERR_STALE_VERSION`).

Concretely, when several domain preconditions could apply to one endpoint, they are evaluated in the numeric order above: for example, on approving an application the compliance check (`ERR_FRANCHISE_IN_VIOLATION`) is evaluated before the renewal milestones check (`ERR_MILESTONES_NOT_MET`); and on filing an application, all well-formedness and existence checks precede the stale-version check.

### 2.9. Nested Resource Retrieval and Foreign-Key Filtering

Path parameters are validated left-to-right: a request to a sub-resource path fails with `ERR_NOT_FOUND` at the first path segment whose `id` does not resolve. Two discovery reads expose sub-resources by reverse foreign-key reachability: the assessments produced by a given audit are reachable through that audit's `id`, and each list endpoint accepts optional filters that select records by their foreign keys. Right-of-way permits may be filtered by `franchise_id` and/or `row_segment_id`; build-out milestones, revenue reports, complaints, PEG contributions, and franchise applications by `franchise_id`; and audits by `franchise_id` and/or `target_report_id`.

### 2.10. Segregation of Duties

The authority user who finalizes an audit becomes the issuer of the resulting assessment, recorded as `issued_by_user_id`. That same user is forbidden from later waiving the assessment: a waiver whose `X-User-ID` equals the assessment's `issued_by_user_id` is rejected with `ERR_SEGREGATION_OF_DUTIES` (403). A different `FranchiseAuthority` user must perform the waiver.

## 3. Business Logic & Workflows

### 3.1. Granting and Operating a Franchise

A `FranchiseAuthority` grants a franchise by supplying the operator's legal name in `operator_name`, the service territory in `territory_name`, the total dwelling units in the territory in `homes_in_territory` (at least 1, and the denominator for build-out density), the public right-of-way extent in `road_miles` (greater than 0), the franchise fee fraction in `fee_rate_pct` (greater than 0 and at most 0.05, i.e. up to five percent of gross), and the term bounds `term_start_date` and `term_end_date` (the end must be strictly after the start). An optional `peg_fee_per_sub_cents` captures a per-subscriber PEG/I-Net capital support fee in cents (at least 0, defaulting to 0). A new grant is created at `lifecycle_status` `DRAFT` and `compliance_status` `COMPLIANT`, with `version` 1, `unresolved_complaint_count` 0, and `homes_passed` 0.

Activating a grant advances it from `DRAFT` to `ACTIVE`; it is defined only from `DRAFT`. Revoking a grant advances it from `ACTIVE` to `REVOKED`, a terminal lifecycle state; it is defined only from `ACTIVE`. Curing a franchise moves the compliance axis from `IN_VIOLATION` to `CURED`, resets `unresolved_complaint_count` to 0, and releases every `HELD` application on the franchise back to `SUBMITTED`; it is defined only when `compliance_status` is `IN_VIOLATION`. Any transition attempted from a state where it is not defined is rejected with `ERR_INVALID_STATE`.

Reading a franchise returns the record including its computed `total_owed_cents` and `peg_credit_cents`. A dedicated summary view returns `total_owed_cents`, `peg_credit_cents`, `compliance_status`, `lifecycle_status`, and `unresolved_complaint_count` for at-a-glance compliance and fiscal standing.

The **total owed** to the authority is computed on read and refreshed whenever a report or assessment changes. It is the sum of two parts: across every revenue report of the franchise whose status is `ACCEPTED`, the fee still outstanding on that report (its `fee_due_cents` minus its `amount_paid_cents`); plus, across every assessment of the franchise whose status is `ISSUED` or `DISPUTED`, that assessment's outstanding balance (its `total_cents` minus its `amount_paid_cents`). Reports in `ADJUSTED` status are deliberately excluded from the first part, because their underpayment is already carried by the assessment — counting both would double-count the same delta. Issuing an assessment and then waiving it therefore leaves `total_owed_cents` exactly where it stood before the assessment existed.

The **PEG credit** is likewise computed on read and refreshed on PEG record and void. It is the sum of `amount_cents` across every PEG contribution of the franchise whose status is `RECORDED`. Recording a contribution and then voiding it leaves `peg_credit_cents` unchanged from its pre-record value.

### 3.2. Right-of-Way Segments and Permits

Before any operator can occupy public right-of-way, an authority registers the segments. A `RowSegment` carries a human `name` (for example, "Main St 100-400 block"), a `length_miles` (greater than 0), the count of homes fronting it in `homes_along` (at least 0), and the owning `jurisdiction` (defaulting to "CITY"). A `RowSegment` is a reference record: it has no lifecycle beyond creation, so it carries `id` and `created_at`, plus `updated_at` and `version` like every other entity.

An `Operator` requests right-of-way use by naming the franchise in `franchise_id`, the segment in `row_segment_id`, the occupation window bounds `window_start` (inclusive) and `window_end` (exclusive, and strictly after `window_start`), and the construction `purpose` (for example, "aerial strand" or "conduit"). A permit is created at `status` `REQUESTED`. Two preconditions gate creation. First, the target franchise's `lifecycle_status` must be `ACTIVE`; otherwise the request is rejected with `ERR_FRANCHISE_NOT_ACTIVE`. Second, the requested window must not collide with any existing permit on the **same** `row_segment_id` whose status is `REQUESTED` or `APPROVED`.

Windows are treated as half-open intervals, and a mandatory clearance gap of 24 hours must separate any two permits on the same segment. A new permit collides with an existing one unless the new window begins at least 24 hours after the existing window ends, or the existing window begins at least 24 hours after the new window ends. Exactly 24 hours of gap is permitted; anything less collides and the create is rejected with `ERR_PERMIT_WINDOW_OVERLAP`.

An authority decides a requested permit by supplying `decision` as either `APPROVE` or `REJECT`. Approval is defined only from `REQUESTED` and additionally requires the franchise's `lifecycle_status` to still be `ACTIVE` (else `ERR_FRANCHISE_NOT_ACTIVE`); it advances the permit to `APPROVED` and records the deciding user in `decided_by_user_id`. Rejection is defined only from `REQUESTED`, advances the permit to `REJECTED`, and records `decided_by_user_id`. Both `APPROVED` and `REJECTED` are terminal. Permits may be read individually and listed with the `franchise_id` and `row_segment_id` filters.

### 3.3. Build-Out and Density Milestones

An authority sets a build-out obligation by creating a `BuildoutMilestone` for a franchise, naming it in `label` (for example, "Year-2 60% density"), giving a `deadline_date`, and specifying the `required_pct` — the fraction of the territory's homes that must be passed by the deadline (greater than 0 and at most 1). At creation the system snapshots `required_homes` as the required fraction times the franchise's `homes_in_territory`, rounded **up** to the next whole home. The milestone opens at `status` `PENDING`, with `homes_passed_certified`, `provisional_damage_cents`, and `final_damage_cents` all 0.

The operator certifies progress by supplying `homes_passed`, the count of dwellings passed as of the certification. Whether a certification is **interim** or **final** is decided entirely by the logical clock relative to the milestone's `deadline_date`. Liquidated damages are computed the same way in both cases: the shortfall is the required homes minus the certified `homes_passed`, but never less than zero, and the damage is that shortfall multiplied by 2,500 cents (25 dollars) per unpassed home. Whether the milestone is met is decided by comparing the fraction of homes passed — `homes_passed` divided by the franchise's `homes_in_territory` — against `required_pct`, with the boundary inclusive: the milestone is met when the fraction passed is at least `required_pct`.

An **interim** certification occurs when the clock is strictly before `deadline_date`. It keeps the milestone in `PENDING`, writes the computed damage into `provisional_damage_cents` (a refundable, provisional figure recomputed on every interim certification), sets `homes_passed_certified` to the input, updates the franchise's `homes_passed` to the certified count, and stamps `last_certified_at` from the clock. A **final** certification occurs when the clock is at or after `deadline_date` and is terminal. If the fraction passed meets `required_pct`, the milestone becomes `MET` and `final_damage_cents` is set to 0. If it falls short, the milestone becomes `MISSED` and `final_damage_cents` is set to the computed shortfall damage — a non-refundable figure. In either final case `homes_passed_certified` and the franchise's `homes_passed` are updated and `last_certified_at` is stamped. The `provisional_damage_cents` from the last interim certification is retained rather than cleared, so both the provisional and final figures remain observable on the terminal milestone. Updating the franchise's `homes_passed` on any certification (interim or final) does not increment the franchise's `version` or refresh its `updated_at`; only the certified milestone's own `version` is bumped. Certifying a milestone that is not `PENDING` is rejected with `ERR_INVALID_STATE`. Milestones may be read individually and listed with the `franchise_id` filter.

### 3.4. Revenue Reporting and Fee Payment

An operator files a revenue report for a period by naming the franchise in `franchise_id`, the period bounds `period_start_date` and `period_end_date` (the end strictly after the start), and three gross-revenue figures in cents, each at least 0: `residential_gross_cents`, `commercial_gross_cents`, and `advertising_gross_cents`. On filing, the system computes `fee_due_cents` from the reported grosses and the franchise's `fee_rate_pct`, sets `fee_basis` to `AS_FILED`, and opens the report at `status` `FILED` with `amount_paid_cents` 0.

The fee is computed line item by line item: the residential gross times the fee rate, rounded half up to a whole cent; the commercial gross times the fee rate, rounded half up; the advertising gross times the fee rate, rounded half up; and then the three rounded amounts are added to yield `fee_due_cents`. Each line is rounded before the sum — the total is never produced by summing the raw products and rounding once.

An authority accepts a filed report, advancing it from `FILED` to `ACCEPTED`; acceptance is defined only from `FILED`. Once accepted, the operator pays the outstanding fee by supplying `amount_cents`, which must equal exactly the report's outstanding balance — its `fee_due_cents` minus its `amount_paid_cents`. A mismatch is rejected with `ERR_PAYMENT_AMOUNT_MISMATCH`. A successful payment adds `amount_cents` to `amount_paid_cents` and advances the report to `PAID`; payment is defined only from `ACCEPTED`. A `PAID` report is not the end of the line — it can still be pulled under audit. The `ADJUSTED` state, reached only through an audit finding, is terminal. Reports may be read individually and listed with the `franchise_id` filter.

### 3.5. Audits, Assessments, and the Finding Cascade

An authority opens an audit against a specific report by naming the franchise in `franchise_id`, the report in `target_report_id`, and the closed coverage interval `period_start_date` through `period_end_date` (the end at or after the start). Opening an audit requires the target report to be in `ACCEPTED` or `PAID`; it remembers the report's prior status, moves the report to `UNDER_AUDIT`, and opens the audit at `status` `OPEN`. A new audit period must not overlap any existing audit on the same `franchise_id`. Audit periods are **closed** date intervals with no clearance buffer: two audits overlap when the later of their two start dates is at or before the earlier of their two end dates, so even a single shared endpoint date counts as an overlap and the create is rejected with `ERR_AUDIT_PERIOD_OVERLAP`.

Finalizing an audit takes a `finding` of either `CLEAN` or `FINDING`, and is defined only from `OPEN`. On finalize, the system records `finalized_by_user_id` and stamps `finalized_at` from the clock. A **clean** finalize moves the audit to `COMPLETED_CLEAN` and restores the target report to whatever status it held before the audit — `ACCEPTED` or `PAID`.

A **finding** finalize additionally supplies the audited grosses `audited_gross_residential_cents`, `audited_gross_commercial_cents`, and `audited_gross_advertising_cents`. A finding is only legitimate when the total audited gross strictly exceeds the total reported gross of the target report; if it does not exceed it, the finalize is rejected with `ERR_AUDIT_NO_UNDERPAYMENT`. A valid finding moves the audit to `COMPLETED_FINDING` and drives a three-hop cascade:

- **Hop 1 — Assessment.** A new `Assessment` is created at `status` `ISSUED`, linked to the finalized audit through `audit_id`, with `issued_by_user_id` copied from the audit's `finalized_by_user_id`. Its `principal_cents` is the audited fee (computed from the audited grosses exactly as the fee formula computes it — each audited line times the rate, rounded half up, then summed) minus the target report's `amount_paid_cents`. Its `days_late` is the whole number of days from the target report's `period_end_date` to the audit's `finalized_at`. Its `interest_cents` is the principal times a daily interest rate of 0.0005 (five hundredths of one percent per day) times `days_late`, rounded half up. Its `underpayment_pct` is the principal divided by the target report's `amount_paid_cents` — the fee previously paid — and it selects the penalty tier: when the underpayment fraction is at least 0.10, the penalty is 15 percent of principal; otherwise when it is at least 0.05, the penalty is 10 percent of principal; otherwise it is 5 percent of principal. When the target report's `amount_paid_cents` is 0 (an audited report accepted but never paid, so the fraction is undefined), `underpayment_pct` is reported as 0.0 and the top tier applies — the 15 percent penalty. That raw penalty is rounded half up and then capped so that `penalty_cents` is the lesser of the raw penalty and 5,000,000 cents (50,000 dollars). The assessment's `total_cents` is the sum of `principal_cents`, `interest_cents`, and `penalty_cents`, and its `amount_paid_cents` starts at 0.
- **Hop 2 — Report.** The target report advances from `UNDER_AUDIT` to `ADJUSTED`, its `fee_basis` becomes `AS_AUDITED`, and its `fee_due_cents` is recomputed from the audited grosses (the same per-line-rounded-then-summed formula, now over the audited figures). The audited fee differs from the filed fee precisely when the audited gross differs from the reported gross.
- **Hop 3 — Franchise.** The franchise's compliance axis flips from `COMPLIANT` or `CURED` to `IN_VIOLATION` (which in turn holds every `SUBMITTED` application, moving it to `HELD`), and `total_owed_cents` is recomputed.

The operator may dispute an issued assessment, moving it from `ISSUED` to `DISPUTED`; dispute is defined only from `ISSUED`. The operator pays an assessment by supplying `amount_cents`, which must equal the assessment's `total_cents` exactly (else `ERR_PAYMENT_AMOUNT_MISMATCH`); a valid payment sets `amount_paid_cents` to `total_cents`, advances the assessment to `PAID`, and recomputes the franchise's `total_owed_cents` (the paid assessment thereby leaves the outstanding set). Payment is defined from `ISSUED` or `DISPUTED`. An authority waives an assessment from `ISSUED` or `DISPUTED`, subject to the segregation-of-duties rule of Section 2.10; a waiver moves the assessment to `WAIVED` and recomputes `total_owed_cents` so the waived assessment leaves the outstanding set — the compensating action that returns total owed to its pre-issue value. Both `PAID` and `WAIVED` are terminal. The audited grosses recorded on the audit are findings only and do not themselves alter the franchise. The assessments produced by an audit are discoverable through that audit, and any assessment may be read individually.

### 3.6. Customer Complaints and Escalation

A `Resident` files a complaint against a franchise by naming it in `franchise_id`, choosing a `category` of `SERVICE_INTERRUPTION`, `BILLING`, or `OTHER`, and providing a free-text `description`. On filing, the server stamps `filed_at` from the clock, records the filer's identifier in `complainant_id`, opens the complaint at `status` `OPEN`, and computes the `sla_deadline` by adding the category's SLA window to `filed_at`: 24 hours for `SERVICE_INTERRUPTION`, 72 hours for `BILLING`, and 168 hours (one week) for `OTHER`.

The complaint lifecycle is cyclic. An operator resolves a complaint from `OPEN`, `REOPENED`, or `ESCALATED` by supplying a `resolution_note`; resolution moves it to `RESOLVED` and records the note, and if the complaint was in `ESCALATED` immediately before, the franchise's `unresolved_complaint_count` is decremented by 1. The original resident may reopen a resolved complaint, moving it from `RESOLVED` to `REOPENED`; reopening is defined only from `RESOLVED` and only for the caller whose `X-User-ID` equals the stored `complainant_id`. A reopen attempt by a resident whose `X-User-ID` does not match the stored `complainant_id` is rejected with `ERR_UNAUTHORIZED` (403), and that identity check is evaluated before the `RESOLVED`-state check. A resolved complaint that is no longer pursued may become `CLOSED`, a terminal state that admits no further transition; resolve-reopen may otherwise cycle indefinitely.

An authority may escalate a complaint from `OPEN` or `REOPENED`, but only once its SLA has actually been breached — the clock must be strictly past `sla_deadline`. Escalation attempted at or before the deadline is rejected with `ERR_SLA_NOT_BREACHED`. A successful escalation moves the complaint to `ESCALATED`, stamps `escalated_at` from the clock, and increments the franchise's `unresolved_complaint_count` by 1. If that count reaches at least 2 escalated complaints, the franchise's compliance flips to `IN_VIOLATION` — which itself holds every `SUBMITTED` application on the franchise. Complaints may be read individually (also by the filing resident) and listed with the `franchise_id` filter.

### 3.7. PEG/I-Net Contributions

An operator records a PEG/I-Net capital contribution against a franchise by naming it in `franchise_id`, giving the `amount_cents` (strictly greater than 0), and optionally a `contribution_type` of `CAPITAL_GRANT` (the default) or `INET`. The contribution is created at `status` `RECORDED` and immediately increases the franchise's `peg_credit_cents`. An authority may void a recorded contribution by supplying a `voided_reason`; voiding is defined only from `RECORDED`, moves the contribution to `VOIDED` (terminal), records the reason, and recomputes `peg_credit_cents` so the voided contribution leaves the credited set. Contributions may be read individually and listed with the `franchise_id` filter.

### 3.8. Transfers and Renewals

An operator initiates a change of the grant by filing a `FranchiseApplication` naming the franchise in `franchise_id`, an `application_type` of `TRANSFER` or `RENEWAL`, and the optimistic-concurrency token `expected_franchise_version` described in Section 2.5. A `TRANSFER` application must include the proposed `transferee_name`; omitting it is rejected with `ERR_TRANSFEREE_REQUIRED`. A `RENEWAL` application must include a `proposed_term_end_date`; omitting it is rejected with `ERR_TERM_REQUIRED`. On successful filing the server stamps `submitted_at` from the clock, computes the `decision_deadline` as `submitted_at` plus 120 days, and opens the application at `status` `SUBMITTED` with `decision` unset. Filing also **supersedes** any prior application still in `SUBMITTED` on the same franchise, moving that prior application to `WITHDRAWN`. A `RENEWAL` filing additionally moves the franchise's lifecycle from `ACTIVE` to `RENEWAL_PENDING`.

An authority decides a submitted application by supplying `decision` as `APPROVE` or `DENY`, recording the deciding user in `decided_by_user_id`. Approval is defined only from `SUBMITTED` and is blocked while the franchise's `compliance_status` is `IN_VIOLATION` (rejected with `ERR_FRANCHISE_IN_VIOLATION`). For a `RENEWAL` approval there is a further cross-entity precondition, evaluated after the compliance check: every build-out milestone of the franchise must be in `MET`; if any milestone is not met, the approval is rejected with `ERR_MILESTONES_NOT_MET`. A successful approval sets `status` to `APPROVED` and `decision` to `APPROVE`; for a `TRANSFER` it moves the franchise lifecycle to `TRANSFERRED` and sets `operator_name` to the `transferee_name`; for a `RENEWAL` it moves the franchise lifecycle to `RENEWED` and sets the franchise's `term_end_date` to the `proposed_term_end_date`. A denial sets `status` to `DENIED` and `decision` to `DENY`; for a `RENEWAL`, denial reverts the franchise lifecycle from `RENEWAL_PENDING` back to `ACTIVE`.

If the authority lets the clock run strictly past the `decision_deadline` without deciding, the operator may invoke deemed approval on a still-`SUBMITTED` application. Deemed approval is defined only from `SUBMITTED` and only when the clock is strictly past `decision_deadline`; invoking it at or before that deadline, or from any state other than `SUBMITTED`, is rejected as an invalid-state condition with `ERR_INVALID_STATE`. A valid deemed approval moves the application to `DEEMED_APPROVED` and applies the very same lifecycle side-effects as an explicit approval (a `TRANSFER` transfers the franchise and copies the transferee name; a `RENEWAL` renews it and adopts the proposed term end). A `RENEWAL` reaching `APPROVED` or `DEEMED_APPROVED` is what drives the franchise from `RENEWAL_PENDING` to `RENEWED`; a `TRANSFER` reaching `APPROVED` or `DEEMED_APPROVED` drives it from `ACTIVE` or `RENEWAL_PENDING` to `TRANSFERRED`.

An application in `HELD` — held because the franchise went into violation — cannot be approved, denied, or deemed while held; it is released back to `SUBMITTED` only when the franchise is cured. The terminal application states are `APPROVED`, `DENIED`, `DEEMED_APPROVED`, and `WITHDRAWN`. Applications may be read individually and listed with the `franchise_id` filter.

## 4. Endpoint Definitions

Creation endpoints that mint a new resource return HTTP 201; all other successful reads and state-changing operations return HTTP 200. The logical-clock endpoint returns 200. Authorization is enforced per the roles listed below.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/_clock/set_current_utc` | Set the server logical clock | FranchiseAuthority |
| POST | `/franchises` | Grant (create) a franchise in DRAFT | FranchiseAuthority |
| GET | `/franchises/{id}` | Read a franchise including computed totals | FranchiseAuthority, Operator |
| GET | `/franchises/{id}/summary` | Computed compliance/fee summary | FranchiseAuthority, Operator |
| POST | `/franchises/{id}/activate` | Activate a granted franchise | FranchiseAuthority |
| POST | `/franchises/{id}/revoke` | Revoke an active franchise | FranchiseAuthority |
| POST | `/franchises/{id}/cure` | Cure a franchise in violation | FranchiseAuthority |
| POST | `/row-segments` | Register a right-of-way segment | FranchiseAuthority |
| GET | `/row-segments/{id}` | Read a right-of-way segment | FranchiseAuthority, Operator |
| POST | `/row-permits` | Request right-of-way use | Operator |
| GET | `/row-permits/{id}` | Read a right-of-way permit | FranchiseAuthority, Operator |
| GET | `/row-permits` | List permits (filter by franchise/segment) | FranchiseAuthority, Operator |
| POST | `/row-permits/{id}/decide` | Approve or reject a requested permit | FranchiseAuthority |
| POST | `/buildout-milestones` | Set a build-out/density milestone | FranchiseAuthority |
| GET | `/buildout-milestones/{id}` | Read a build-out milestone | FranchiseAuthority, Operator |
| GET | `/buildout-milestones` | List milestones (filter by franchise) | FranchiseAuthority, Operator |
| POST | `/buildout-milestones/{id}/certify` | Certify homes passed (interim or final) | Operator |
| POST | `/revenue-reports` | File a period gross-revenue report | Operator |
| GET | `/revenue-reports/{id}` | Read a revenue report | FranchiseAuthority, Operator |
| GET | `/revenue-reports` | List reports (filter by franchise) | FranchiseAuthority, Operator |
| POST | `/revenue-reports/{id}/accept` | Accept a filed report | FranchiseAuthority |
| POST | `/revenue-reports/{id}/pay` | Pay the outstanding franchise fee | Operator |
| POST | `/audits` | Open an audit of a specific report | FranchiseAuthority |
| GET | `/audits/{id}` | Read an audit | FranchiseAuthority, Operator |
| GET | `/audits` | List audits (filter by franchise/report) | FranchiseAuthority, Operator |
| POST | `/audits/{id}/finalize` | Finalize an audit clean or with a finding | FranchiseAuthority |
| GET | `/audits/{id}/assessments` | Assessments produced by this audit | FranchiseAuthority, Operator |
| GET | `/assessments/{id}` | Read an assessment | FranchiseAuthority, Operator |
| POST | `/assessments/{id}/pay` | Pay an assessment in full | Operator |
| POST | `/assessments/{id}/dispute` | Dispute an issued assessment | Operator |
| POST | `/assessments/{id}/waive` | Waive an assessment (not the issuer) | FranchiseAuthority |
| POST | `/complaints` | File a customer complaint | Resident |
| GET | `/complaints/{id}` | Read a complaint | FranchiseAuthority, Operator, Resident |
| GET | `/complaints` | List complaints (filter by franchise) | FranchiseAuthority, Operator |
| POST | `/complaints/{id}/resolve` | Resolve a complaint | Operator |
| POST | `/complaints/{id}/escalate` | Escalate an SLA-breached complaint | FranchiseAuthority |
| POST | `/complaints/{id}/reopen` | Reopen a resolved complaint | Resident |
| POST | `/peg-contributions` | Record a PEG/I-Net contribution | Operator |
| GET | `/peg-contributions/{id}` | Read a PEG contribution | FranchiseAuthority, Operator |
| GET | `/peg-contributions` | List contributions (filter by franchise) | FranchiseAuthority, Operator |
| POST | `/peg-contributions/{id}/void` | Void a recorded contribution | FranchiseAuthority |
| POST | `/franchise-applications` | File a transfer or renewal application | Operator |
| GET | `/franchise-applications/{id}` | Read a franchise application | FranchiseAuthority, Operator |
| GET | `/franchise-applications` | List applications (filter by franchise) | FranchiseAuthority, Operator |
| POST | `/franchise-applications/{id}/decide` | Approve or deny a submitted application | FranchiseAuthority |
| POST | `/franchise-applications/{id}/deem` | Invoke deemed approval after the deadline | Operator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_NOT_FRANCHISE_OWNER` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_FRANCHISE_NOT_ACTIVE` | 409 |
| `ERR_SLA_NOT_BREACHED` | 409 |
| `ERR_FRANCHISE_IN_VIOLATION` | 409 |
| `ERR_MILESTONES_NOT_MET` | 409 |
| `ERR_PERMIT_WINDOW_OVERLAP` | 409 |
| `ERR_AUDIT_PERIOD_OVERLAP` | 409 |
| `ERR_PAYMENT_AMOUNT_MISMATCH` | 402 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_AUDIT_NO_UNDERPAYMENT` | 409 |
| `ERR_TRANSFEREE_REQUIRED` | 400 |
| `ERR_TERM_REQUIRED` | 400 |
| `ERR_VALIDATION_PERIOD_INVALID` | 400 |
