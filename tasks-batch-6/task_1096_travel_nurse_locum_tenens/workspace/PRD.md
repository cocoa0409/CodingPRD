# Travel-Nurse & Locum-Tenens Agency API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the back-office platform of a travel-nurse and locum-tenens staffing agency. The agency places traveling clinicians — registered nurses, nurse practitioners, physicians, nurse anesthetists, and therapists — into short-term assignments at client facilities, most commonly on the industry-standard thirteen-week term. Each placement is a small business unit in its own right: it carries a signed contract, a credentialing packet that must clear compliance review, a stream of weekly timesheets, and an earnings ledger that reconciles what the agency bills the facility against what it pays the clinician. The platform's job is to keep all of those moving parts consistent under a strict segregation-of-duties model, so that no single operator can both create and approve the same financial or compliance event.

Two themes run through every workflow. The first is **compliance auditing**: a clinician may only work an assignment when a valid license covers the facility's state for the entire contracted term and when a full set of required credential documents has been primary-source verified. The second is **ledger reconciliation**: every dollar the platform records must satisfy a money-partition invariant in which the gross bill always equals the pay cost plus the margin, and every guaranteed hour must always be accounted for as consumed, remaining, or waived. Because the agency operates on thin margins, the platform additionally enforces a firm margin floor at contract-execution time and lifts weekly bills whenever contracted rates would fall below that floor.

The system is deterministic and testable end-to-end. It runs on a **logical clock** rather than wall-clock time, so that credentialing expiries, cancellation-notice windows, and payroll periods can be exercised precisely. All timestamps, notice-day computations, and week-window checks read from that logical clock.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that apply across every endpoint. Business-specific behavior lives in Section 3.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the operational capacity under which the caller acts. The platform recognizes exactly six roles: `PlatformAdmin`, `Recruiter`, `CredentialingSpecialist`, `Clinician`, `FacilityManager`, and `PayrollAdmin`. If either header is missing or empty, or if `X-User-Role` is not one of these six exact strings, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the acting role is not permitted to invoke the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

Four of the six roles are **opaque operator identities**: for `PlatformAdmin`, `Recruiter`, `CredentialingSpecialist`, and `PayrollAdmin`, the `X-User-ID` is an operator identifier that is not tied to any persisted entity. The server records such an id where a workflow demands it — for example as `verified_by_user_id` on a license or credential item, `submitted_by_user_id` and `cleared_by_user_id` on a credential packet, or `opened_by_user_id` and `posted_by_user_id` on a payroll run — but it never compares it to any entity's `id`. It is these recorded operator ids that the segregation-of-duties checks compare against one another.

The remaining two roles are **entity-backed**. When `X-User-Role` is `Clinician`, the `X-User-ID` is the `id` of the acting `Clinician` row; any ownership check on a resource that references a clinician compares that resource's clinician foreign key to `X-User-ID`. When `X-User-Role` is `FacilityManager`, the `X-User-ID` is the `id` of the acting `Facility` row; ownership checks compare the resource's facility foreign key to `X-User-ID`. Concretely, a `Clinician` may only act on an assignment whose `clinician_id` equals its `X-User-ID`, and a `FacilityManager` may only act on an assignment whose `facility_id` equals its `X-User-ID`; a mismatch yields `ERR_OWNERSHIP_VIOLATION` (HTTP 403). This ownership check runs on timesheet creation, timesheet transitions, contract transitions, assignment cancellation, extension opening, extension responses, credential-item attachment, and credential-packet transitions.

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

All list (array) endpoints accept two optional query parameters, `limit` and `offset`. The `limit` defaults to 10, must be at least 1, and may not exceed 100. The `offset` defaults to 0 and must not be negative. A `limit` outside the range 1 through 100, or a negative `offset`, is a body/parameter shape error and is rejected with `ERR_VALIDATION` (HTTP 400). List results are always sorted by `created_at` in ascending order. The `meta` block of a list response reports `limit`, `offset`, `total_count` (the total number of matching rows before the page window is applied), and `has_more` (true when rows remain beyond the current page).

### 2.4. Common Resource Properties, Timestamps, and Versioning

Every persisted resource carries a server-minted `id`, which is a UUID with no type prefix. The client never supplies an `id`. Most resources also carry three further common properties: `created_at`, `updated_at`, and `version`. Both `created_at` and `updated_at` are ISO 8601 UTC timestamps with exactly three fractional digits (of the form `YYYY-MM-DDTHH:MM:SS.mmmZ`). The `version` is an integer that starts at 1 on creation and increases by exactly 1 on every mutation, including mutations produced as cascaded side effects of some other operation. Any mutation that changes a resource also refreshes its `updated_at` and increments its `version`.

One entity is the exception: the `PerDiemLocality` reference row does not carry the common mutation fields. A `PerDiemLocality` exposes only `id` and `created_at`; it has no `updated_at` and no `version`, because per-diem rate rows are immutable once filed (a new effective-dated row is added rather than an existing one edited).

All timestamps are stamped from the **logical clock**, never from wall-clock time. This includes `created_at`, `updated_at`, `verified_at`, `clinician_signed_at`, and `resolved_at`. The logical clock is advanced by an administrative test-driving capability that accepts a target instant. Before that capability is first invoked, the logical clock reads exactly `2026-05-01T00:00:00Z`; it never falls back to real wall-clock time. The clock's calendar date is also the "today" used for cancellation-notice arithmetic and for the timesheet week-window checks.

### 2.5. Money, Hours, Dates, and Rounding Conventions

All monetary amounts are integer counts of **cents**; no floating-point money is ever persisted. All hour quantities are decimal numbers carrying at most two fractional digits, and comparisons on hours are exact decimal comparisons. Calendar dates are strings in `YYYY-MM-DD` form with no time component; the whole-day difference between two calendar dates is the later date minus the earlier date counted in whole calendar days.

Three rounding operators recur throughout the calculations. Rounding a cent amount **half up** means rounding to the nearest whole cent with ties broken away from zero. **Ceiling to whole cents** means rounding up to the next whole cent. **Integer ceiling division** of a non-negative numerator by a positive denominator yields the smallest integer greater than or equal to the exact quotient, computed as the numerator plus the denominator minus one, integer-divided by the denominator; it is used wherever a percentage floor must never be undershot by a rounding artifact. Percentages (margin ratios) are stored rounded half up to four decimal places, but a **stored percentage is never the basis of a threshold comparison** — every threshold gate is evaluated with exact integer arithmetic so that a rounding artifact can never flip the outcome.

### 2.6. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency on their parent entity's `version`, because each is a legitimately repeatable operation whose prior effect a later caller could silently overwrite.

Opening an extension negotiation against an assignment requires the request to carry `expected_assignment_version`, holding the client's last observed `version` of that `Assignment`. Because opening a new negotiation supersedes any prior open negotiation on the same assignment (the prior one is withdrawn), a second, later open would otherwise succeed on stale terms; therefore, if `expected_assignment_version` does not equal the assignment's current `version`, the request is rejected with `ERR_STALE_ASSIGNMENT_VERSION` (HTTP 412).

Revising a contract requires the request to carry `expected_contract_version`, holding the client's last observed `version` of that `Contract`. Revision is a repeatable self-loop, so a later revise would observe a legal from-state and succeed, overwriting rate terms the caller never saw; therefore, if `expected_contract_version` does not equal the contract's current `version`, the request is rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412). No other endpoint accepts or requires a version field.

### 2.7. The Two Independent Assignment Dimensions and Cascade Discipline

An `Assignment` is unusual in that it carries **two independent state dimensions** on one row. The `staffing_status` dimension tracks the placement lifecycle through `DRAFT`, `PENDING_START`, `ACTIVE`, and the terminal states `COMPLETED` and `CANCELLED`. The `compliance_status` dimension tracks credentialing posture through `PENDING_CREDENTIALS`, `CLEARED`, and `SUSPENDED`, and evolves entirely separately: a transition that advances one dimension leaves the other untouched unless a rule explicitly says otherwise.

Many operations mutate more than one entity. When a single call has secondary effects — a contract voiding when its assignment cancels, an assignment's compliance suspending when a credential item is revoked, a clinician's counters moving when a statement finalizes — every affected entity is mutated in the same request, and each such mutation refreshes that entity's `updated_at` and increments its `version`. Section 3 describes these cascades in full; the governing principle here is that they are immediate and synchronous, never deferred, and the money-partition and guaranteed-hour partition invariants hold after both a forward action and its compensating reversal.

### 2.8. Validation Ordering

When a single request could fail more than one check, the checks are evaluated in a fixed ascending priority order, and the **first** check that fails determines the returned error. The order is:

1. Authentication — both headers present and non-empty and `X-User-Role` among the six roles, else `ERR_UNAUTHENTICATED`.
2. Authorization — the acting role is permitted on the endpoint, else `ERR_UNAUTHORIZED`.
3. Path existence — every resource named in the URL path exists, validated left-to-right along the path, else the matching not-found error.
4. Ownership — for entity-backed roles, the acting `X-User-ID` owns the target, else `ERR_OWNERSHIP_VIOLATION`.
5. Request shape — required fields present, types correct, enum members legal, `state_code` exactly two uppercase letters, dates parseable, Sunday constraints, `daily_hours` well-formed, `term_weeks` within range, pagination bounds — else `ERR_VALIDATION`.
6. Body foreign keys — every foreign key in the body resolves to an existing row, else the matching not-found error.
7. State admissibility — the target's current state admits the requested transition, else `ERR_INVALID_TRANSITION`, `ERR_ASSIGNMENT_NOT_ACTIVE`, or `ERR_STATEMENT_ALREADY_POSTED`.
8. Optimistic concurrency — the supplied expected parent version equals the parent's current `version`, else `ERR_STALE_ASSIGNMENT_VERSION` or `ERR_STALE_CONTRACT_VERSION`.
9. Segregation of duties, else `ERR_SEGREGATION_OF_DUTIES`.
10. Compliance-suspension guard, else `ERR_COMPLIANCE_SUSPENDED`.
11. Packet-cleared guard, else `ERR_PACKET_NOT_CLEARED`.
12. License-coverage guard, else `ERR_LICENSE_COVERAGE_MISSING`.
13. Contract-executed guard, else `ERR_CONTRACT_NOT_EXECUTED`.
14. Timesheet week-window (temporal), else `ERR_WEEK_OUTSIDE_TERM`.
15. Clinician schedule conflict (temporal), else `ERR_CLINICIAN_SCHEDULE_CONFLICT`.
16. Duplicate timesheet week (temporal), else `ERR_DUPLICATE_TIMESHEET_WEEK`.
17. Facility capacity, else `ERR_FACILITY_CAPACITY_EXCEEDED`.
18. Hours limits, else `ERR_HOURS_LIMIT_EXCEEDED`.
19. Term limit on extension acceptance, else `ERR_TERM_LIMIT_EXCEEDED`.
20. Negotiation-round limit on counter, else `ERR_NEGOTIATION_ROUNDS_EXHAUSTED`.
21. Margin floor on contract execution, else `ERR_MARGIN_BELOW_FLOOR`.

The specific trigger conditions for each check live with the workflow it guards in Section 3; the ordering above is what disambiguates which error surfaces when several conditions are simultaneously unmet.

### 2.9. The Margin-Floor Principle

The agency will not execute a placement whose whole-term projected economics fall below a **22 percent** margin floor, and it will not bill a work week at a rate that produces less than that same 22 percent margin. Both gates are evaluated with exact integer arithmetic. At contract execution the projected whole-term margin passes only when the projected margin in cents multiplied by 100 is at least the projected gross bill in cents multiplied by 22; otherwise execution is rejected with `ERR_MARGIN_BELOW_FLOOR`. On a weekly bill the same floor is enforced by lifting the bill up to the smallest amount that holds it — see Section 3.6. The stored four-decimal margin percentages are display values only and are never the comparison basis.

### 2.10. Nested Reads and Reverse-Reachability

Several read endpoints expose a child collection reachable from a parent id embedded in the URL path (for example, the licenses of a clinician, the timesheets of an assignment, or the items of a credential packet). For any such path, the parent segments are validated left-to-right: if a parent id in the path does not resolve, the corresponding not-found error is returned before any child filtering is attempted. Which error surfaces depends on which resource the unresolved id addresses: `ERR_CLINICIAN_NOT_FOUND`, `ERR_LICENSE_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_PACKET_NOT_FOUND`, `ERR_CREDENTIAL_ITEM_NOT_FOUND`, `ERR_TIMESHEET_NOT_FOUND`, `ERR_PAYROLL_RUN_NOT_FOUND`, or `ERR_EXTENSION_NOT_FOUND` — and the same not-found errors apply to any body foreign key (for instance `assignment_id` or `clinician_id`) that fails to resolve. These reverse-reachability reads accept the standard pagination parameters and, where noted in Section 4, additional filter parameters.

## 3. Business Logic & Workflows

### 3.1. Reference Data, Clinicians, and Licensure

The `PlatformAdmin` owns the platform's reference data and the logical clock. A test-driving capability advances the logical clock to a supplied `to_iso8601` instant and returns the new `current_utc`; it mutates no entity. The same role files GSA per-diem rate rows and registers client facilities.

A per-diem rate row records a GSA `locality_code` (for example, a code like `PHX-AZ`), the `state_code` it belongs to, a `daily_lodging_cents` lodging allowance, a `daily_mie_cents` meals-and-incidental-expenses allowance, and an `effective_from` calendar date from which the row applies inclusively. A locality is deliberately allowed to have many rows — one per effective date — and a `locality_code` is therefore not unique on its own; the correct row for a given basis date is chosen chronologically (Section 3.6). A facility is registered with its `name`, `state_code`, an accounts-payable `billing_contact_email`, and a `per_diem_locality_code` that is matched by value against per-diem rows (it is a locality code, not an id reference). A facility may optionally declare `is_compact_member`, which is false unless supplied and marks the facility's state as recognizing multi-state compact licensure, and `max_concurrent_travelers`, its aggregate capacity, which defaults to 2 and must be at least 1. That capacity is the greatest number of overlapping `PENDING_START` or `ACTIVE` placements the facility will host at once.

A `Recruiter` registers a traveling clinician with a `full_name`, a `discipline` (one of `RN`, `NP`, `PHYSICIAN`, `CRNA`, `THERAPIST`), a `specialty` used to match assignments (one of `ICU`, `ER`, `MED_SURG`, `OR`, `L_AND_D`, `TELEMETRY`, `PSYCH`, `HOSPITALIST`), an `employment_type` (either `W2_EMPLOYEE`, which carries employer burden, or `CONTRACTOR_1099`, which does not), and a `primary_residence_state` given as exactly two uppercase letters — this is the clinician's compact-privilege home state. The optional `tax_home_verified` flag defaults to false and gates whether per-diem stipends may be paid tax-free. On registration the clinician's derived `status` is initialized to `AVAILABLE` (its other possible values being `ON_ASSIGNMENT` and `INACTIVE`), the `active_assignment_count` is initialized to 0, and both the `ytd_taxable_wages_cents` and `ytd_nontaxable_stipend_cents` counters are initialized to 0. The `status` is recomputed from the clinician's assignments, and `active_assignment_count` is the count of the clinician's assignments whose `staffing_status` is `PENDING_START` or `ACTIVE`. The two year-to-date counters are running sums over the clinician's earnings statements whose ledger `status` is `FINALIZED` or `POSTED`.

A `Recruiter` files a state license for a clinician, supplying the owning `clinician_id`, the issuing `state_code` (exactly two uppercase letters), the `license_type` it grants (one of `RN`, `NP`, `PHYSICIAN`, `CRNA`, `THERAPIST`), the board-issued `license_number`, the `expires_on` calendar date on which it lapses, and an optional `is_compact` flag (false unless supplied) marking it as a multi-state compact license. A newly filed license is created in `PENDING_VERIFICATION`. A `CredentialingSpecialist` drives the license through its verification machine by supplying a target `to` state. Moving a `PENDING_VERIFICATION` or `SUSPENDED` license to `VERIFIED` records `verified_by_user_id` (the specialist's operator id) and stamps `verified_at` from the logical clock. A `VERIFIED` license may be moved to `SUSPENDED` (which drops it out of the coverage candidate set) and back to `VERIFIED` again, an unbounded reinstatement loop, or moved to the terminal `EXPIRED` state. Any requested license transition that is not an outgoing edge of the license's current state is rejected with `ERR_INVALID_TRANSITION`.

### 3.2. Placing a Clinician: Assignment, Contract, and Packet Creation

Creating a placement is a `Recruiter` operation that, in a single call, builds three linked resources: the `Assignment`, its `Contract`, and its `CredentialPacket`. The request supplies the `clinician_id` and `facility_id` being paired, the placement `specialty`, the `required_license_type` the placement demands, the `start_date`, the `term_weeks`, the `weekly_guaranteed_hours`, the `base_pay_rate_cents_per_hour` the clinician is paid, the `bill_rate_cents_per_hour` the facility is billed, and an optional `shift` pattern (`DAY`, `NIGHT`, or `ROTATING`, defaulting to `DAY`). The placement `specialty` must equal the clinician's `specialty`. The `start_date` must be a Sunday, and `term_weeks` must be between 1 and 26 inclusive — the minimum term is one week and the maximum is twenty-six weeks; the standard term is thirteen weeks. If the body is malformed in any of these ways the call is rejected with `ERR_VALIDATION`; if the `clinician_id` does not resolve the error is `ERR_CLINICIAN_NOT_FOUND`, and if the `facility_id` does not resolve the error is `ERR_FACILITY_NOT_FOUND`.

Upon creation the assignment's `staffing_status` is `DRAFT` and its `compliance_status` is `PENDING_CREDENTIALS`. Its `end_date` is computed as the `start_date` plus `term_weeks` times seven days, minus one day, so that the term spans exactly the intended number of whole weeks; the `end_date` is recomputed whenever `term_weeks` later changes. The system then resolves licensure over the whole `[start_date, end_date]` window and pins the winner onto `covering_license_id`; if no license covers the window the whole creation is rejected with `ERR_LICENSE_COVERAGE_MISSING`. Alongside the assignment, a `Contract` is created in `DRAFT` carrying the same `term_weeks`, `weekly_guaranteed_hours`, `base_pay_rate_cents_per_hour`, and `bill_rate_cents_per_hour`; its `revision_count` starts at 0. A `CredentialPacket` is created in `DRAFT` with both readiness scores at 0 and both blocking counts at 5. The assignment's `guaranteed_hours_total` and `guaranteed_hours_remaining` are both set to `weekly_guaranteed_hours` multiplied by `term_weeks`, while `guaranteed_hours_consumed` and `guaranteed_hours_waived` start at 0. Finally the forward-looking projection is computed onto the assignment's `projected_gross_bill_cents`, `projected_pay_cost_cents`, `projected_margin_cents`, and `projected_margin_pct` fields (Section 3.3). The `extension_round_count` starts at 0.

**License coverage resolution.** A covering license is chosen from the clinician's licenses by a deterministic selection. A license is a candidate only when it belongs to the assignment's clinician, its `license_type` equals the assignment's `required_license_type`, its `status` is `VERIFIED` (licenses that are `PENDING_VERIFICATION`, `SUSPENDED`, or `EXPIRED` are excluded), its `expires_on` is on or after the coverage end date (an inclusive comparison), and it grants authority in the facility's state by one of two paths: **direct licensure**, where the license's `state_code` equals the facility's `state_code`; or **compact privilege**, where the license's `is_compact` is true, the facility's `is_compact_member` is true, and the license's `state_code` equals the clinician's `primary_residence_state`. Among the candidates, the winner is chosen by ranking first by coverage kind, with direct licensure preferred over compact privilege; then by latest `expires_on`; then, as a final deterministic tie-break, by earliest `created_at`. The resource `id` is never used as a tie-break. When the candidate set is empty the resolution fails with `ERR_LICENSE_COVERAGE_MISSING` (HTTP 422). The coverage end date is the assignment's `end_date`, except when an extension is being accepted, in which case it is the new, longer `end_date`.

**Scheduling and capacity guards on placement.** Two temporal guards protect a new placement. First, no other assignment of the same clinician whose `staffing_status` is `DRAFT`, `PENDING_START`, or `ACTIVE` may overlap the new assignment's date interval once that interval is expanded by a two-day travel gap on both sides: a conflict exists when the new assignment's `start_date` minus two days is on or before the other assignment's `end_date` and the other assignment's `start_date` is on or before the new assignment's `end_date` plus two days (closed, buffered intervals). A conflict is rejected with `ERR_CLINICIAN_SCHEDULE_CONFLICT`. Second, the facility's aggregate capacity is enforced: counting the facility's assignments whose `staffing_status` is `PENDING_START` or `ACTIVE` and whose **unbuffered** closed interval `[start_date, end_date]` intersects the new assignment's interval, that count must be strictly less than the facility's `max_concurrent_travelers`; if it has already reached that capacity the placement is rejected with `ERR_FACILITY_CAPACITY_EXCEEDED`.

### 3.3. The Contract: Signature, Revision, and the Projected-Margin Gate

Each placement is papered by exactly one `Contract`, linked by its `assignment_id`, moving through a signature lifecycle: `DRAFT`, `SENT_FOR_SIGNATURE`, `COUNTERSIGN_REQUESTED`, `FULLY_EXECUTED`, and the terminal `VOIDED`. The default `term_weeks` is thirteen and the default `weekly_guaranteed_hours` is thirty-six; `term_weeks` must be between 1 and 26, and `weekly_guaranteed_hours` must be greater than 0 and at most 84.

**Revision.** A `Recruiter` may revise the contract's commercial terms while it is in `DRAFT` or `COUNTERSIGN_REQUESTED`; a revision out of `COUNTERSIGN_REQUESTED` returns the contract to `DRAFT`, and a revision out of `DRAFT` is a repeatable self-loop that leaves it in `DRAFT`. The revise request carries `expected_contract_version` plus the replacement `term_weeks`, `weekly_guaranteed_hours`, `base_pay_rate_cents_per_hour`, and `bill_rate_cents_per_hour`. Because revision is repeatable, it is guarded by optimistic concurrency: if `expected_contract_version` does not match the contract's current `version`, the revise is rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412), preventing a caller from overwriting rate terms it never observed. A successful revision replaces those four terms, increments `revision_count` by 1, and increments the contract's `version`. It then recomputes the assignment's `term_weeks`, `end_date`, `guaranteed_hours_total`, and `guaranteed_hours_remaining`, and re-derives the forward-looking projection onto the assignment's `projected_*` fields. Attempting to revise a contract in any other state is rejected with `ERR_INVALID_TRANSITION`.

**Signature.** A `Recruiter` drives a `DRAFT` contract to `SENT_FOR_SIGNATURE` (permitted only while the assignment's `staffing_status` is still `DRAFT`) by supplying that target `to` state. From `SENT_FOR_SIGNATURE`, the acting `Clinician` — whose id must equal the assignment's `clinician_id` — may either request a countersignature, moving the contract to `COUNTERSIGN_REQUESTED` and recording the supplied `countersign_note`, or fully execute it. Requesting a countersignature closes back into the negotiation loop, since a subsequent revision returns the contract to `DRAFT`. Any signature move that is not an outgoing edge of the current state is rejected with `ERR_INVALID_TRANSITION`.

**Execution and its margin gate.** Fully executing a contract is a `Clinician` action out of `SENT_FOR_SIGNATURE` and is gated by the margin floor. Execution is permitted only when the assignment's projected whole-term margin holds the floor, tested with exact integer arithmetic: the `projected_margin_cents` multiplied by 100 must be at least the `projected_gross_bill_cents` multiplied by 22. If it is below, execution is rejected with `ERR_MARGIN_BELOW_FLOOR` (HTTP 422). On success the contract moves to `FULLY_EXECUTED`, `clinician_signed_at` is stamped from the logical clock, and the effect bubbles up to the assignment: its `staffing_status` advances from `DRAFT` to `PENDING_START`, the clinician's `active_assignment_count` is increased by 1, and the clinician's `status` becomes `ON_ASSIGNMENT`. Each of these mutations increments the affected entity's `version`.

**The projected (whole-term) economics.** The `projected_*` fields are a forward-looking estimate at contracted rates, recomputed whenever the contract terms change — on placement creation, on contract revision, and on extension acceptance. The projection assumes exactly `weekly_guaranteed_hours` of straight time every week for the whole term, with no overtime and no callback, and it never applies the weekly margin-floor uplift, so it can legitimately report a percentage below the floor — that is precisely the gate. To build it, the system first selects the per-diem row effective on the assignment's `start_date` and forms a projected weekly stipend: when `weekly_guaranteed_hours` is at least 32, the stipend is the smaller of the sum of that row's `daily_lodging_cents` and `daily_mie_cents` multiplied by seven days, or the weekly cap of 250000 cents; when `weekly_guaranteed_hours` is below 32, the projected stipend is 0. The projected weekly taxable amount is `weekly_guaranteed_hours` multiplied by `base_pay_rate_cents_per_hour`, rounded half up, plus the projected stipend when the clinician's `tax_home_verified` is false. The projected weekly employer burden is that taxable amount multiplied by 0.185 and rounded half up when the clinician is a `W2_EMPLOYEE`, and 0 for a `CONTRACTOR_1099`. The projected weekly non-taxable stipend is the projected stipend when `tax_home_verified` is true, else 0. The projected weekly pay cost is the sum of the taxable amount, the non-taxable stipend, and the burden; the projected weekly bill is `weekly_guaranteed_hours` multiplied by `bill_rate_cents_per_hour`, rounded half up, at the contracted rate only with no uplift. Multiplying each weekly figure by `term_weeks` gives `projected_pay_cost_cents` and `projected_gross_bill_cents`; `projected_margin_cents` is the projected gross bill minus the projected pay cost; and `projected_margin_pct` is the projected margin divided by the projected gross bill, rounded half up to four decimal places, as a display value only.

### 3.4. Credentialing: The Compliance Packet and Its Documents

Every placement's `CredentialPacket`, linked by its `assignment_id`, is the compliance file that must clear before the clinician may start work. It moves through `DRAFT`, `SUBMITTED`, `UNDER_REVIEW`, `CHANGES_REQUESTED`, `CLEARED`, and the terminal `REJECTED`. Both a `Clinician` and a `CredentialingSpecialist` may attach documents and drive the packet to `SUBMITTED`; only a `CredentialingSpecialist` may drive it to `UNDER_REVIEW`, `CHANGES_REQUESTED`, `CLEARED`, or `REJECTED`. That a specialist may submit on the clinician's behalf is deliberate — it is what makes the clearing segregation-of-duties check reachable.

**Documents.** A `Clinician` or `CredentialingSpecialist` attaches a credential document to the packet, supplying its `item_type`, an opaque `document_ref`, and an optional `expires_on` date (null means the document never lapses). The document's owning `packet_id` is the packet it is added to. There are seven document classes — `BLS_CERT`, `IMMUNIZATION_RECORD`, `BACKGROUND_CHECK`, `DRUG_SCREEN`, `LICENSE_VERIFICATION`, `TB_TEST`, and `FIT_TEST` — of which the first five are the **required** types; `TB_TEST` and `FIT_TEST` are tracked but ignored by the readiness scores. A new item is created in `PENDING` and its verification `status` moves through `VERIFIED`, `REJECTED`, `REVOKED`, or `EXPIRED`. A `CredentialingSpecialist` drives one item by supplying a target `to`: a `PENDING` item may become `VERIFIED` (recording `verified_by_user_id`) or `REJECTED`; a `REJECTED` item may return to `PENDING` for re-upload; and a `VERIFIED` item may become the terminal `REVOKED` or `EXPIRED`. Attaching an item, and every item transition, recomputes the parent packet's readiness for both bases. An item transition that is not an outgoing edge of the item's current state is rejected with `ERR_INVALID_TRANSITION`.

**Dual-basis readiness.** Readiness is scored against the five required types under two different validity dates. A required type is **satisfied** on a given basis date when at least one item of that type on the packet is `VERIFIED` and either has no `expires_on` or has an `expires_on` on or after that basis date (an inclusive comparison); because one qualifying item suffices, a superseding re-upload with a later `expires_on` repairs the type. The count of satisfied required types out of five, multiplied by 100 and divided by 5 and rounded half up, is the readiness score. Under the **start-date basis**, the basis date is the assignment's `start_date`: this yields `readiness_score_start_basis` and, as five minus the satisfied count, `blocking_item_count_start_basis`. Under the **full-term basis**, the basis date is the assignment's `end_date`: this yields `readiness_score_full_term_basis` and `blocking_item_count_full_term_basis`. Because a document may be valid on the start date but expire before the end date, the full-term basis can score strictly lower than the start-date basis on the identical packet — the start-date basis gates packet clearance, while the stricter full-term basis gates activation.

**Review and clearance.** A `CredentialingSpecialist` drives a `SUBMITTED` packet to `UNDER_REVIEW`, and from `UNDER_REVIEW` may request changes, clear, or reject. Requesting changes moves the packet to `CHANGES_REQUESTED` and increments `revision_round` by 1, but only while `revision_round` is still below 3; once it has reached three revision rounds the only legal move out of `UNDER_REVIEW` is rejection, and a further change request is rejected with `ERR_INVALID_TRANSITION`. From `CHANGES_REQUESTED` the packet is resubmitted back to `SUBMITTED` — a cyclic revision loop bounded at three rounds — recording the resubmitting `submitted_by_user_id`. Clearing a packet requires that it is `UNDER_REVIEW`, that `blocking_item_count_start_basis` is 0 under the start-date basis (else `ERR_PACKET_NOT_CLEARED`), and that the acting `X-User-ID` differs from the packet's `submitted_by_user_id` (else `ERR_SEGREGATION_OF_DUTIES`). On clearance the packet records `cleared_by_user_id`, and the effect bubbles up to the assignment's compliance dimension: `compliance_status` advances from `PENDING_CREDENTIALS` (or from `SUSPENDED` after remediation) to `CLEARED`, leaving `staffing_status` untouched. Rejection moves an `UNDER_REVIEW` packet to the terminal `REJECTED`.

**Cascade A — a revoked credential suspends the placement.** When a `CredentialingSpecialist` revokes or expires a previously `VERIFIED` item, the packet's readiness is recomputed, and if a required type is no longer satisfied on the start-date basis while the packet is `CLEARED`, a synchronized cascade fires: the packet moves from `CLEARED` to `CHANGES_REQUESTED` and its `revision_round` increments; the assignment's `compliance_status` moves from `CLEARED` to `SUSPENDED`; and every open extension negotiation on that assignment whose `status` is `PROPOSED` or `COUNTERED` is withdrawn, each stamping its `resolved_at`. This suspension may be lifted and re-applied any number of times: from `SUSPENDED`, once the packet is again `UNDER_REVIEW` with `blocking_item_count_start_basis` at 0, clearing it returns `compliance_status` to `CLEARED`.

### 3.5. Activation

A `Recruiter` activates a placement to advance its `staffing_status` from `PENDING_START` to `ACTIVE`. The state gate admits an assignment that is in `DRAFT` or `PENDING_START`; an assignment already in `ACTIVE`, `COMPLETED`, or `CANCELLED` is rejected here with `ERR_INVALID_TRANSITION`. A `DRAFT` assignment survives that state gate but is then stopped by the contract gate: activation requires the linked contract's `status` to be `FULLY_EXECUTED`, and a `DRAFT` assignment (whose contract is not executed) is rejected with `ERR_CONTRACT_NOT_EXECUTED` — this is exactly how that error becomes reachable. Activation further requires that the credential packet's `status` is `CLEARED` and its `blocking_item_count_full_term_basis` is 0 under the stricter full-term basis, else `ERR_PACKET_NOT_CLEARED`; and that license coverage still resolves over the assignment's `[start_date, end_date]` window, else `ERR_LICENSE_COVERAGE_MISSING`. On success the assignment's `staffing_status` becomes `ACTIVE`, its `covering_license_id` is re-pinned to the current winner of coverage resolution, and its `version` increments; the `compliance_status` dimension is untouched.

### 3.6. Timesheets and Weekly Settlement

A `Clinician` — whose id must equal the assignment's `clinician_id` — submits one work week by supplying the `assignment_id`, the `week_start_date`, a `daily_hours` array, and an optional `callback_hours` value (defaulting to 0). The `week_start_date` must be a Sunday and opens the seven-day work week, whose window is the half-open interval from `week_start_date` up to but not including seven days later. The `daily_hours` array must hold exactly seven non-negative numbers, index 0 being that Sunday through index 6 being the following Saturday. A timesheet may only be filed while the parent assignment's `staffing_status` is `ACTIVE` (else `ERR_ASSIGNMENT_NOT_ACTIVE`) and its `compliance_status` is not `SUSPENDED` (else `ERR_COMPLIANCE_SUSPENDED`). The week must fall inside the term: `week_start_date` must be on or after the assignment's `start_date`, the week's last day (six days after `week_start_date`) must be on or before the assignment's `end_date`, and `week_start_date` must be on or before the logical clock's calendar date; a violation yields `ERR_WEEK_OUTSIDE_TERM`. No other timesheet of the same assignment whose `status` is `SUBMITTED`, `APPROVED`, or `DISPUTED` may already cover that half-open week window — equivalently, none may share the identical `week_start_date` — else `ERR_DUPLICATE_TIMESHEET_WEEK`. Finally, every entry of `daily_hours` must be at most 24 and their sum at most 84, else `ERR_HOURS_LIMIT_EXCEEDED`. A newly filed timesheet is created directly in `SUBMITTED` with its hour classification already applied.

**Weekly hour classification.** From the seven `daily_hours` entries the system derives `total_raw_hours` as their sum. Daily overtime is the sum, across the seven days, of each day's hours above twelve (each day contributing the excess over the twelve-hour daily overtime threshold, never a negative amount). Weekly overtime is the amount by which `total_raw_hours` exceeds forty, the weekly overtime threshold (never negative). The `overtime_hours` is the **larger** of the daily-overtime total and the weekly-overtime figure — not their sum; the rule that yields more wins. The `regular_hours` is `total_raw_hours` minus `overtime_hours`. The `days_worked` is the count of `daily_hours` entries strictly greater than 0. The `callback_hours` input is entirely separate: it never enters `total_raw_hours`, never contributes to either overtime figure, and never affects `days_worked`. This classification is computed on timesheet creation and again on any resubmission after a dispute, and it is frozen when the week is approved.

**Approval and the settlement cascade (Cascade B).** A `FacilityManager` — whose id must equal the assignment's `facility_id` — approves a `SUBMITTED` week by supplying the target `to` state, but only while the assignment is `ACTIVE` (else `ERR_ASSIGNMENT_NOT_ACTIVE`) and not `SUSPENDED` in its compliance dimension (else `ERR_COMPLIANCE_SUSPENDED`). Approval sets the timesheet to `APPROVED`, records `approved_by_user_id`, and creates one earnings statement whose `kind` is `WEEKLY` in the `FINALIZED` ledger state, wiring in the statement's `timesheet_id`, `assignment_id`, and `clinician_id`, and setting its `period_key_date` to the `week_start_date`. The statement's `billable_hours` for a `WEEKLY` statement is `regular_hours` plus `overtime_hours`. Building that statement runs four calculations in a pinned order.

*Per-diem selection.* The stipend uses the per-diem row for the facility, chosen chronologically: among all `PerDiemLocality` rows whose `locality_code` equals the facility's `per_diem_locality_code` and whose `effective_from` is on or before the basis date (the `week_start_date`), the winner is the one with the latest `effective_from`, breaking ties by earliest `created_at`. If no such row exists, both `daily_lodging_cents` and `daily_mie_cents` are treated as 0, the stipend is 0, and `stipend_variant` is `NONE`.

*Stipend (dual variant).* Let the worked hours be `regular_hours` plus `overtime_hours` (callback excluded) and the daily total be the chosen row's `daily_lodging_cents` plus `daily_mie_cents`. When worked hours are at least 32 — the full-week stipend threshold, an inclusive comparison — the `stipend_variant` is `FULL_WEEK_ACCRUAL` and the stipend is the smaller of the daily total multiplied by seven calendar days or the weekly cap of 250000 cents; a full week accrues all seven days of lodging and M&IE regardless of how many days were actually worked. When worked hours are below 32 the `stipend_variant` is `DAILY_PRORATED` and the stipend is the smaller of the daily total multiplied by `days_worked` or the same 250000-cent cap, so at identical daily rates a short week yields a strictly smaller stipend. The same stipend amount is paid either way; only the tax bucket differs. When the clinician's `tax_home_verified` is true, the `non_taxable_stipend_cents` equals the stipend and nothing is added to taxable wages; when it is false, `non_taxable_stipend_cents` is 0 and the stipend amount is instead added into taxable wages.

*Pay cost.* Each pay line is rounded to whole cents before the lines are summed. The regular pay is `regular_hours` multiplied by `base_pay_rate_cents_per_hour`, rounded half up. The overtime pay is `overtime_hours` multiplied by `base_pay_rate_cents_per_hour` multiplied by the overtime multiplier of 1.5, rounded half up. The callback pay is `callback_hours` multiplied by `base_pay_rate_cents_per_hour` multiplied by the callback multiplier of 2.0, rounded half up. The `taxable_wages_cents` is the sum of those three rounded lines plus the stipend amount when it was routed to wages (that is, when the tax home is unverified). The `burden_cents` is the `taxable_wages_cents` multiplied by 0.185 and rounded half up for a `W2_EMPLOYEE`, and 0 for a `CONTRACTOR_1099`. The `total_pay_cost_cents` is `taxable_wages_cents` plus `non_taxable_stipend_cents` plus `burden_cents`.

*Bill and margin.* The `contracted_bill_cents` is billed at contracted rates with the same per-line rounding: `regular_hours` times `bill_rate_cents_per_hour` rounded half up, plus `overtime_hours` times `bill_rate_cents_per_hour` times 1.5 rounded half up, plus `callback_hours` times `bill_rate_cents_per_hour` times 2.0 rounded half up. The smallest bill that holds the 22 percent margin floor — the required bill — is the `total_pay_cost_cents` multiplied by 100 and integer-ceiling-divided by 78 (the exact integer form of dividing the pay cost by 0.78, so the floor is never undershot). The `gross_bill_cents` is the larger of `contracted_bill_cents` and that required bill, and `margin_uplift_applied` is true exactly when the gross bill was lifted above the contracted bill. Finally `gross_margin_cents` is `gross_bill_cents` minus `total_pay_cost_cents`, and `margin_pct` is `gross_margin_cents` divided by `gross_bill_cents`, rounded half up to four decimal places. On every statement the money partition holds: the gross bill equals the pay cost plus the gross margin.

*Ledger roll-up and auto-completion.* Because the new statement is `FINALIZED`, the assignment's realized ledger is re-summed over its statements whose ledger `status` is `FINALIZED` or `POSTED` (reversed statements are excluded): `realized_gross_bill_cents` is the sum of their `gross_bill_cents`, `realized_pay_cost_cents` the sum of their `total_pay_cost_cents`, `realized_margin_cents` the sum of their `gross_margin_cents`, and `realized_margin_pct` is the realized margin divided by the realized gross bill rounded half up to four decimal places, or exactly 0 when the realized gross bill is 0. The assignment's `guaranteed_hours_consumed` increases by the smaller of the week's worked hours (`regular_hours` plus `overtime_hours`) or the contract's `weekly_guaranteed_hours`, and `guaranteed_hours_remaining` decreases by that same amount. The clinician's `ytd_taxable_wages_cents` and `ytd_nontaxable_stipend_cents` increase by the statement's amounts. If `guaranteed_hours_remaining` has now reached exactly 0, the assignment's `staffing_status` advances from `ACTIVE` to `COMPLETED`, the clinician's `active_assignment_count` decrements, and when that count reaches 0 the clinician's `status` returns to `AVAILABLE`. Throughout, the guaranteed-hour partition holds: consumed plus remaining plus waived always equals `guaranteed_hours_total`, which equals `weekly_guaranteed_hours` times `term_weeks`.

**Dispute and resubmission.** A `FacilityManager` may instead dispute a `SUBMITTED` week, moving it to `DISPUTED` and recording the `dispute_reason`. The owning `Clinician` then resubmits it back to `SUBMITTED`, optionally supplying replacement `daily_hours` and `callback_hours`; on resubmission the hour classification is recomputed from the replacement hours, the same hour limits are re-checked (else `ERR_HOURS_LIMIT_EXCEEDED`), and the `dispute_reason` is cleared. This dispute–resubmit pair may repeat without bound.

**Void and reversal.** A `PayrollAdmin` may void an `APPROVED` timesheet by supplying the target `to` state, provided the linked earnings statement is still `FINALIZED`; if that statement has already been `POSTED` it is immutable and the void is rejected with `ERR_STATEMENT_ALREADY_POSTED`. Voiding sets the timesheet to `VOIDED` and the linked statement's ledger `status` from `FINALIZED` to `REVERSED`, dropping it from every finalized-or-posted roll-up. Every ledger increment from approval is then exactly undone: the assignment's `realized_gross_bill_cents`, `realized_pay_cost_cents`, and `realized_margin_cents` decrease by that statement's amounts and `realized_margin_pct` is recomputed; `guaranteed_hours_consumed` decreases and `guaranteed_hours_remaining` increases by the statement's consumed hours; and the clinician's `ytd_taxable_wages_cents` and `ytd_nontaxable_stipend_cents` decrease by the statement's amounts. If the assignment was `COMPLETED` and `guaranteed_hours_remaining` becomes greater than 0, its `staffing_status` reverts from `COMPLETED` to `ACTIVE`, the clinician's `active_assignment_count` increases, and the clinician's `status` becomes `ON_ASSIGNMENT`.

### 3.7. Payroll Runs

A `PayrollAdmin` opens a pay period by supplying its `period_start_date` and `period_end_date`, both inclusive. Opening a run creates it in `OPEN`, records `opened_by_user_id`, and immediately claims every unclaimed earnings statement that is eligible: a statement is claimed when its ledger `status` is `FINALIZED`, its `payroll_run_id` is still null, and its `period_key_date` falls on or after `period_start_date` and on or before `period_end_date`. Reversed statements, already-posted statements, and statements already claimed by another run are excluded. Claimed statements are processed in ascending `created_at` order, each having its `payroll_run_id` set to this run. The run's `statement_count` is the number claimed, `total_pay_cost_cents` the sum of their `total_pay_cost_cents`, `total_gross_bill_cents` the sum of their `gross_bill_cents`, and `total_margin_cents` the sum of their `gross_margin_cents`; the partition invariant holds, with `total_gross_bill_cents` equal to `total_pay_cost_cents` plus `total_margin_cents`.

The run then moves through `OPEN`, `LOCKED`, and `POSTED` by a supplied target `to`. Locking an `OPEN` run freezes its `statement_count` and three totals at their current values. Posting is permitted only out of `LOCKED` and enforces segregation of duties: the acting `X-User-ID` must differ from `opened_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`. Posting records `posted_by_user_id` and flips every claimed statement whose ledger `status` is `FINALIZED` to `POSTED`, making each such statement immutable. A statement individually transitions from `FINALIZED` to `POSTED` only as part of posting the run that claimed it, and only while that run is `LOCKED`. Attempting to post a run that is still `OPEN`, or any other move that is not an outgoing edge of the run's current state, is rejected with `ERR_INVALID_TRANSITION`.

### 3.8. Extension Negotiations

Either a `Recruiter` or the owning `Clinician` may open an extension negotiation against an assignment. The open request carries `expected_assignment_version` plus the proposed terms: `proposed_additional_weeks` (at least 1), `proposed_pay_rate_cents_per_hour`, and `proposed_bill_rate_cents_per_hour`. Opening is guarded by optimistic concurrency on the assignment's `version` (Section 2.6): a stale `expected_assignment_version` is rejected with `ERR_STALE_ASSIGNMENT_VERSION`. An open may not proceed while the assignment's `compliance_status` is `SUSPENDED`, which yields `ERR_COMPLIANCE_SUSPENDED`. A successful open creates the request in `PROPOSED` with `round_count` at 1, and sets both `initiated_by_role` and `last_actor_role` to the acting role; any prior extension request on the same assignment whose `status` is `PROPOSED` or `COUNTERED` is superseded and set to `WITHDRAWN`, each stamping `resolved_at`, and the assignment's `version` increments.

An open negotiation is answered by supplying an `action` of `COUNTER`, `ACCEPT`, or `DECLINE`. The responding role must differ from `last_actor_role` (the same role may not move twice in a row), else `ERR_SEGREGATION_OF_DUTIES`. A `COUNTER` flips the request between `PROPOSED` and `COUNTERED`, replaces the `proposed_*` terms with the counter terms, increments `round_count`, and updates `last_actor_role`; it is legal only while `round_count` is below three, else `ERR_NEGOTIATION_ROUNDS_EXHAUSTED`. This proposed–countered alternation continues until three negotiation rounds are used. A `DECLINE` moves the request to `DECLINED` and stamps `resolved_at`.

Accepting a request (from `PROPOSED` or `COUNTERED`) requires that the assignment's `staffing_status` is `PENDING_START` or `ACTIVE`, that the assignment's `term_weeks` plus `proposed_additional_weeks` does not exceed 26 (else `ERR_TERM_LIMIT_EXCEEDED`), and that license coverage still resolves over the assignment's start date through its new, longer end date (else `ERR_LICENSE_COVERAGE_MISSING`). On acceptance the request moves to `ACCEPTED` and stamps `resolved_at`; the assignment's `term_weeks` increases by `proposed_additional_weeks`, its `end_date` is recomputed, and its `extension_round_count` increments. The assignment's `guaranteed_hours_total` and `guaranteed_hours_remaining` each increase by the contract's `weekly_guaranteed_hours` multiplied by `proposed_additional_weeks`. The contract's `term_weeks`, `base_pay_rate_cents_per_hour`, and `bill_rate_cents_per_hour` are replaced by the accepted terms and the contract's `version` increments. Finally the assignment's `covering_license_id` is re-pinned and its `projected_*` fields are recomputed. An extension request is also withdrawn by the system when its assignment is suspended or cancelled, as described in Sections 3.4 and 3.9.

### 3.9. Cancellation and Settlement

A `FacilityManager` — whose id must equal the assignment's `facility_id` — cancels a placement by supplying an `effective_date` and a `cancellation_reason`. Cancellation is permitted while the assignment's `staffing_status` is `DRAFT`, `PENDING_START`, or `ACTIVE`, and the `effective_date` must be on or after the logical clock's calendar date. On cancellation the assignment moves to `CANCELLED`, recording `cancellation_effective_date`, `cancellation_notice_days` (the whole calendar days from the clock's date to the effective date, measured at the moment of cancellation), and `cancellation_penalty_cents`.

**Settlement.** The notice days are the whole calendar days between the clock date and the `effective_date`. When notice is at least thirty days — the cancellation-notice window, an inclusive comparison, so exactly thirty days is sufficient — the shortfall is zero weeks; otherwise the shortfall is the difference of thirty minus the notice days, divided by seven and rounded up to a whole number of weeks. The shortfall hours are the smaller of the contract's `weekly_guaranteed_hours` multiplied by the shortfall weeks, or the assignment's current `guaranteed_hours_remaining`. Guaranteed hours are then settled by a waterfall: `guaranteed_hours_consumed` increases by the shortfall hours, `guaranteed_hours_waived` increases by the remaining hours minus the shortfall hours, and `guaranteed_hours_remaining` is set to 0. When the shortfall hours are 0, `cancellation_penalty_cents` is 0 and no statement is created.

When the shortfall hours are greater than 0, a `CANCELLATION_PENALTY` earnings statement is created in the `FINALIZED` ledger state, priced with no stipend: its `stipend_variant` is `NONE`, its `non_taxable_stipend_cents` is 0, its `timesheet_id` is null, its `period_key_date` is the `cancellation_effective_date`, and its `billable_hours` is the shortfall hours. The `taxable_wages_cents` is the shortfall hours multiplied by `base_pay_rate_cents_per_hour`, rounded half up. The `burden_cents` is that amount multiplied by 0.185 and rounded half up for a `W2_EMPLOYEE`, and 0 for a `CONTRACTOR_1099`. The `total_pay_cost_cents` is the taxable wages plus the burden. The `contracted_bill_cents` is the shortfall hours multiplied by `bill_rate_cents_per_hour`, rounded half up; the required bill that holds the 22 percent floor is the total pay cost multiplied by 100 and integer-ceiling-divided by 78; the `gross_bill_cents` is the larger of those two, the `gross_margin_cents` is the gross bill minus the total pay cost, and `cancellation_penalty_cents` is that `gross_bill_cents`. The realized ledger and the clinician's year-to-date counters then absorb this penalty statement.

Cancellation also cascades to the surrounding entities: the linked contract, whether it is in `DRAFT`, `SENT_FOR_SIGNATURE`, `COUNTERSIGN_REQUESTED`, or `FULLY_EXECUTED`, moves to `VOIDED` with its `voided_reason` set to the cancellation reason; the clinician's `active_assignment_count` decrements, and when it reaches 0 the clinician's `status` returns to `AVAILABLE`; and every extension request on the assignment whose `status` is `PROPOSED` or `COUNTERED` is withdrawn. A cancellation from `DRAFT` — where there was no active work — records `cancellation_penalty_cents` as 0 with no penalty statement, sets `guaranteed_hours_waived` to the full `guaranteed_hours_remaining`, and sets `guaranteed_hours_remaining` to 0.

## 4. Endpoint Definitions

Endpoints that create a brand-new resource return HTTP 201; endpoints that read or modify an existing resource (including state transitions) return HTTP 200. Every request body and the field-level behavior of each endpoint are described in Section 3; the table below lists only the routing contract. All paths are literal (the API prefix is the root).

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | /_clock/set_current_utc | Advance the logical clock to a supplied instant | PlatformAdmin |
| POST | /per-diem-localities | File one effective-dated GSA per-diem rate row | PlatformAdmin |
| POST | /facilities | Register a client facility | PlatformAdmin |
| POST | /clinicians | Register a traveling clinician | Recruiter |
| GET | /clinicians/{id} | Read one clinician with counters | Recruiter, CredentialingSpecialist, PayrollAdmin, PlatformAdmin, Clinician, FacilityManager |
| GET | /clinicians/{id}/licenses | List the licenses of one clinician | Recruiter, CredentialingSpecialist, PayrollAdmin, PlatformAdmin, Clinician, FacilityManager |
| POST | /licenses | File a state license for a clinician | Recruiter |
| POST | /licenses/{id}/transition | Drive the license verification machine | CredentialingSpecialist |
| POST | /assignments | Place a clinician (creates assignment, contract, packet) | Recruiter |
| GET | /assignments/{id} | Read one assignment with both dimensions and ledgers | Recruiter, CredentialingSpecialist, PayrollAdmin, PlatformAdmin, Clinician, FacilityManager |
| GET | /assignments | List assignments with filters | Recruiter, CredentialingSpecialist, PayrollAdmin, PlatformAdmin, Clinician, FacilityManager |
| POST | /assignments/{id}/activate | Activate a placement | Recruiter |
| POST | /assignments/{id}/cancel | Cancel a placement and settle | FacilityManager |
| GET | /assignments/{id}/contracts | List the contract of one assignment | Recruiter, CredentialingSpecialist, PayrollAdmin, PlatformAdmin, Clinician, FacilityManager |
| POST | /contracts/{id}/transition | Drive the contract signature machine | Recruiter, Clinician |
| POST | /contracts/{id}/revise | Replace contract terms (OCC-guarded) | Recruiter |
| GET | /assignments/{id}/credential-packets | List the packet of one assignment | Recruiter, CredentialingSpecialist, PayrollAdmin, PlatformAdmin, Clinician, FacilityManager |
| GET | /credential-packets/{id} | Read one packet with both readiness variants | Recruiter, CredentialingSpecialist, PayrollAdmin, PlatformAdmin, Clinician, FacilityManager |
| GET | /credential-packets/{id}/items | List the items of one packet | Recruiter, CredentialingSpecialist, PayrollAdmin, PlatformAdmin, Clinician, FacilityManager |
| POST | /credential-packets/{id}/items | Attach one credential document | Clinician, CredentialingSpecialist |
| POST | /credential-packets/{id}/transition | Drive the packet review machine | Clinician, CredentialingSpecialist |
| POST | /credential-items/{id}/transition | Drive one credential document's verification machine | CredentialingSpecialist |
| POST | /timesheets | Submit one work week | Clinician |
| GET | /assignments/{id}/timesheets | List the timesheets of one assignment | Recruiter, CredentialingSpecialist, PayrollAdmin, PlatformAdmin, Clinician, FacilityManager |
| POST | /timesheets/{id}/transition | Drive the timesheet approval machine | FacilityManager, Clinician, PayrollAdmin |
| GET | /earnings-statements/{id} | Read one earnings statement | Recruiter, CredentialingSpecialist, PayrollAdmin, PlatformAdmin, Clinician, FacilityManager |
| GET | /earnings-statements | List earnings statements with filters | Recruiter, CredentialingSpecialist, PayrollAdmin, PlatformAdmin, Clinician, FacilityManager |
| POST | /payroll-runs | Open a pay period and claim statements | PayrollAdmin |
| POST | /payroll-runs/{id}/transition | Lock or post a payroll run | PayrollAdmin |
| POST | /assignments/{id}/extensions | Open an extension negotiation (OCC-guarded) | Recruiter, Clinician |
| GET | /assignments/{id}/extensions | List the extension requests of one assignment | Recruiter, CredentialingSpecialist, PayrollAdmin, PlatformAdmin, Clinician, FacilityManager |
| POST | /extension-requests/{id}/respond | Counter, accept, or decline a negotiation | Recruiter, Clinician |

## 5. Error Code Catalogue

The trigger condition for each error is described alongside the workflow it guards in Sections 2 and 3.

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_OWNERSHIP_VIOLATION | 403 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_VALIDATION | 400 |
| ERR_CLINICIAN_NOT_FOUND | 404 |
| ERR_FACILITY_NOT_FOUND | 404 |
| ERR_LICENSE_NOT_FOUND | 404 |
| ERR_ASSIGNMENT_NOT_FOUND | 404 |
| ERR_CONTRACT_NOT_FOUND | 404 |
| ERR_PACKET_NOT_FOUND | 404 |
| ERR_CREDENTIAL_ITEM_NOT_FOUND | 404 |
| ERR_TIMESHEET_NOT_FOUND | 404 |
| ERR_PAYROLL_RUN_NOT_FOUND | 404 |
| ERR_EXTENSION_NOT_FOUND | 404 |
| ERR_INVALID_TRANSITION | 409 |
| ERR_ASSIGNMENT_NOT_ACTIVE | 409 |
| ERR_STATEMENT_ALREADY_POSTED | 409 |
| ERR_STALE_ASSIGNMENT_VERSION | 412 |
| ERR_STALE_CONTRACT_VERSION | 412 |
| ERR_COMPLIANCE_SUSPENDED | 409 |
| ERR_PACKET_NOT_CLEARED | 422 |
| ERR_LICENSE_COVERAGE_MISSING | 422 |
| ERR_CONTRACT_NOT_EXECUTED | 422 |
| ERR_WEEK_OUTSIDE_TERM | 422 |
| ERR_CLINICIAN_SCHEDULE_CONFLICT | 409 |
| ERR_DUPLICATE_TIMESHEET_WEEK | 409 |
| ERR_FACILITY_CAPACITY_EXCEEDED | 409 |
| ERR_HOURS_LIMIT_EXCEEDED | 422 |
| ERR_TERM_LIMIT_EXCEEDED | 422 |
| ERR_NEGOTIATION_ROUNDS_EXHAUSTED | 409 |
| ERR_MARGIN_BELOW_FLOOR | 422 |

