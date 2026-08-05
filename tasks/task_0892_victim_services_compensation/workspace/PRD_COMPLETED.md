# Victim Services & Compensation Program API — Product Requirements Document

## 1. Introduction

State victim-compensation programs exist to make crime survivors financially whole when the offender cannot, drawing on a legislatively appropriated fund to reimburse documented losses such as medical bills, lost wages, funeral costs, and mental-health treatment. Running such a program is fundamentally an exercise in reconciliation under scarcity: every dollar promised to one survivor is a dollar removed from a fixed appropriation, collateral insurance must be netted out so the public fund pays only what is truly uncompensated, and monies later recovered from offenders flow back into the fund. This document specifies the REST API that operates a single such program end to end — victim intake and eligibility screening, claim filing and documentation, collateral-source offset, award calculation and disbursement, restitution recovery and subrogation, victim notification and advocacy, and the appeal process that lets a denied determination be reopened.

The system is built around two intertwined disciplines. The first is a **ledger discipline**: the program fund tracks money that has been committed to awards, money that has actually been paid out, and money recovered from offenders, and these three figures are continuously re-derived from the underlying records rather than mutated ad hoc. The second is a **compliance and separation-of-duties discipline**: eligibility is gated on cooperation with law enforcement and on timely filing, sensitive decisions are restricted to specific roles, and the officer who decides an appeal may never be the same person who issued the denial under appeal. Because determinations are time-sensitive — filing deadlines and appeal windows are measured in days — the server runs on a controllable logical clock so that these windows can be exercised deterministically.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, contracts, and cross-cutting principles that apply across the entire API. Unless a later business-logic subsection states an exception, the rules here always hold.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the role under which they act. If either header is missing, or if `X-User-Role` is not one of the recognized role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the acting role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly six roles, spelled precisely as follows: `ProgramAdmin`, `IntakeCounselor`, `Adjudicator`, `FinanceOfficer`, `RecoveryOfficer`, and `AppealsOfficer`. A `ProgramAdmin` configures programs and the logical clock and performs reporting reads. An `IntakeCounselor` intakes victims, files claims and collateral declarations, files appeals, and may submit cases and claims. An `Adjudicator` reviews and determines case eligibility, decides claims, confirms or waives collateral sources, and calculates and approves awards. A `FinanceOfficer` finalizes awards and manages disbursements. A `RecoveryOfficer` runs restitution recoveries and records or voids receipts. An `AppealsOfficer` independently decides appeals. Every role may perform any GET read; write operations are restricted as detailed in the endpoint table of §4 and the workflows of §3.

Each of the six roles carries an **opaque** identity. That is, for every role, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity's `id`, and the server never compares it against an entity primary key for ownership. The server does, however, **record** the acting `X-User-ID` where a workflow demands accountability: when an `Adjudicator` sets a case `INELIGIBLE`, the acting `X-User-ID` is captured as `denied_by_user_id` on the `VictimCase`; when an `Adjudicator` denies a claim, it is captured as `denied_by_user_id` on the `Claim`; and when an `AppealsOfficer` decides an appeal, it is captured as `decided_by_user_id` on the `Appeal`. These recorded identifiers are the basis for the segregation-of-duties rule described in §2.10, not for resource ownership.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of records returned; it defaults to 10, must be at least 1, and may not exceed 100. The `offset` parameter is the number of records to skip and defaults to 0, with a minimum of 0. A `limit` or `offset` outside these bounds is rejected with `ERR_VALIDATION` (HTTP 400).

Unless a specific endpoint says otherwise, every list is sorted by `created_at` in ascending order; because the logical clock can stamp several records with an identical `created_at`, ties are broken by ascending order of creation (server insertion order). Each list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object, where `total_count` is the count of records matching the query before pagination and `has_more` indicates whether records remain beyond the current page.

### 2.4. Common Resource Properties and the Notification Log

Most resources in this system — `Program`, `VictimCase`, `Claim`, `CollateralSource`, `Award`, `Disbursement`, `RestitutionRecovery`, `RecoveryReceipt`, and `Appeal` — carry a common set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps rendered with three fractional digits. The `version` is an integer that begins at 1 on creation and increments by one on every mutation of the resource. Any change to a resource — including recomputation of a derived field — refreshes `updated_at` and increments `version`.

The `Notification` resource is the sole exception: it is an append-only VINE and advocacy event log and therefore carries only `id` and `created_at`. A `Notification` has no `updated_at` and no `version`, because it is never modified after it is written. Each notification records the `case_id` it concerns, a `channel` (one of `VINE`, `EMAIL`, or `LETTER`), an `event_type` (one of `ELIGIBILITY_DECISION`, `CLAIM_DECISION`, `PAYMENT`, `APPEAL_DECISION`, or `CASE_REOPENED`), and a human-readable `message`. Notifications are never created directly by a client; they are produced only as side effects of the workflows described in §3.

### 2.5. Monetary Values and Precision

All monetary amounts in this system are integer counts of cents; there are no fractional cents and no floating-point currency. Field names carrying money end in `_cents` and every such value is a whole number. Where a calculation produces a non-integer intermediate — most notably the weekly wage-replacement benefit, which multiplies a wage by a fractional replacement rate — the result is rounded to a whole number of cents using the **round half up** convention before it is used further. The precise point at which rounding is applied is pinned per calculation in §3 and must be followed exactly, because rounding at a different step changes the final figure. Amount fields are constrained to be at least 0, except a disbursement `amount_cents` and a recovery receipt `amount_cents`, which must be strictly greater than 0; a violation of these bounds is an `ERR_VALIDATION` (HTTP 400).

### 2.6. The Logical Clock and Timestamped Determinations

The server keeps a **logical clock** rather than reading wall-clock time. At startup the clock reads exactly `2026-05-01T00:00:00Z`, and until it is explicitly set it never falls back to real time. A `ProgramAdmin` may advance or set the clock to a supplied instant. The logical clock is the source of every server-stamped time: it drives `created_at` on all resources, the `denied_at` stamp written when a case or claim is denied, and the `filed_at` stamp written when an appeal is filed. Deadline and window computations in §3 (the filing deadline and the appeal window) are evaluated against this clock, comparing whole calendar dates. The clock-setting operation takes a single `to_iso8601` instant to which the clock is moved.

### 2.7. The Program Budget Ledger

Each `Program` exposes four derived budget figures that are always reconciled from the underlying records rather than stored independently. The `budget_committed_cents` is the forward-looking exposure: the sum of `net_award_cents` across every `Award` belonging to the program's cases whose `approval_status` is `CALCULATED`, `APPROVED`, or `FINALIZED`. The `budget_disbursed_cents` is the realized cash-out: the sum of `amount_cents` over every `Disbursement` in status `PAID`. The `budget_recovered_cents` is the total clawed back from offenders: the sum of `amount_cents` over every `RecoveryReceipt` in status `RECORDED`, across the program's cases. The `budget_available_cents` is `total_budget_cents` minus `budget_committed_cents`. These figures are recomputed whenever an award is created or transitioned, a disbursement is transitioned, or a receipt is created or voided, and every such recomputation refreshes the program's `updated_at` and increments its `version`. The distinction between the committed figure (a promise recorded the moment an award is calculated) and the disbursed figure (money that has actually left the fund as disbursements are paid) is central: budget headroom for new awards is governed by the committed figure, not the disbursed one.

### 2.8. Optimistic Concurrency on Award Creation

Because creating an award commits budget against a shared, finite program appropriation, award creation is guarded by optimistic concurrency control on the parent `Program`. A request to create an award must carry `expected_program_version`, the `version` of the `Program` the client last observed. If another award — for any case under the same program — has committed budget and advanced the program's `version` since the client last read it, then `expected_program_version` will be behind the program's current `version`, and the create is rejected with `ERR_STALE_VERSION` (HTTP 412). This prevents a client from calculating an award against a stale view of remaining budget. Award creation is the only operation that takes a version token; no other endpoint accepts or checks `expected_program_version`.

### 2.9. Validation Ordering and Nested Resource Resolution

When several conditions could reject a request, they are evaluated in a fixed priority order so that the returned `error_id` is deterministic. Authentication (`ERR_UNAUTHENTICATED`, 401) is checked first, then authorization against the role matrix (`ERR_UNAUTHORIZED`, 403). Next, the existence of every resource named in the path is verified left-to-right, and then the existence of any foreign-key references carried in the body; an unresolved reference yields the resource-specific not-found error (for example `ERR_PROGRAM_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_COLLATERAL_SOURCE_NOT_FOUND`, `ERR_AWARD_NOT_FOUND`, `ERR_DISBURSEMENT_NOT_FOUND`, `ERR_RECOVERY_NOT_FOUND`, `ERR_RECEIPT_NOT_FOUND`, or `ERR_APPEAL_NOT_FOUND`, each HTTP 404). After existence comes business-referential scoping (`ERR_REFERENCE_MISMATCH`, 409), then state-machine legality (`ERR_INVALID_STATE`, 409), then cross-entity state preconditions, then segregation of duties, then program-closed checks, then the concurrency check, then temporal windows, then the remaining business constraints, and finally field-level shape validation (`ERR_VALIDATION`, 400). Within each workflow in §3, the specific ordering that matters is called out where it is not obvious. For any path that names a resource by identifier, that resource's existence is confirmed before the operation's own preconditions are considered. Every state-changing operation on an existing resource is a transition request that carries a `to_status` naming the target state; a `to_status` that is not reachable from the resource's current state is rejected with `ERR_INVALID_STATE`.

### 2.10. Segregation of Duties on Appeals

The integrity of the appeal process depends on independent review. When an `AppealsOfficer` grants or denies an appeal, the acting `X-User-ID` must differ from the `denied_by_user_id` recorded on the target of the appeal — the denying `Adjudicator` on the case (or on the specific claim, when the appeal names one). If the same user who issued the denial attempts to decide its appeal, the transition is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). This check applies to both the grant and the denial of an appeal, symmetrically.

## 3. Business Logic & Workflows

### 3.1. Establishing a Program Fund

A `ProgramAdmin` opens the system by creating a `Program`, supplying a `name`, the `fiscal_year` the fund covers, the `total_budget_cents` appropriated, and a family of caps: the `overall_case_cap_cents` (the maximum net award payable to any single case) together with four per-category aggregate caps — `medical_cap_cents`, `lost_wage_cap_cents`, `funeral_cap_cents`, and `mental_health_cap_cents`. All budget and cap inputs must be at least 0. A newly created program begins in `status` `OPEN`, with its committed, disbursed, and recovered figures at zero and `budget_available_cents` equal to `total_budget_cents`.

A program runs until the administrator closes it, moving `status` from `OPEN` to `CLOSED`. Closing is only permitted when no `Award` under the program's cases sits in `approval_status` `CALCULATED` or `APPROVED` — that is, every award must be `FINALIZED`, or the program must have no awards at all; otherwise the close is rejected with `ERR_INVALID_STATE`. Once a program is `CLOSED`, any attempt to create a new case or a new award under it is rejected with `ERR_PROGRAM_CLOSED` (HTTP 409).

### 3.2. Victim Intake and Eligibility Determination

An `IntakeCounselor` opens a matter by creating a `VictimCase` under a program, providing the owning `program_id`, the `victim_name`, the `incident_date` on which the qualifying crime occurred, the `crime_type` (one of `ASSAULT`, `HOMICIDE`, `DOMESTIC_VIOLENCE`, `DUI`, `ROBBERY`, `SEXUAL_ASSAULT`, or `OTHER`), a `reported_to_le` boolean indicating whether the crime was reported to law enforcement, an optional `le_report_date` recording when it was reported, an optional `cooperation_status`, and the `filing_date` on which the compensation claim was filed. If `cooperation_status` is omitted it defaults to `PENDING`; the other permitted values are `COOPERATIVE` and `NONCOOPERATIVE`. A case cannot be created under a program that is already `CLOSED` (`ERR_PROGRAM_CLOSED`). On creation the case is in `status` `DRAFT` and its computed `eligibility_status` is `UNDETERMINED`.

The case advances through a review lifecycle. An `IntakeCounselor` submits a `DRAFT` case, moving it `DRAFT → SUBMITTED`. An `Adjudicator` then takes it `SUBMITTED → UNDER_REVIEW`, and from `UNDER_REVIEW` reaches one of two determinations. To rule a case eligible (`UNDER_REVIEW → ELIGIBLE`), two conditions must both hold. First, the crime must have been reported to law enforcement and the survivor must be cooperating — that is, `reported_to_le` is true and `cooperation_status` equals `COOPERATIVE`; if not, the determination is rejected with `ERR_ELIGIBILITY_CRITERIA_NOT_MET` (HTTP 422). Second, the claim must have been filed in time: counting whole days from `incident_date` to `filing_date`, the elapsed count must be at least 0 and at most the filing deadline of 365 days (one year), inclusive at the boundary, so that a filing exactly 365 days out is timely and a filing at 366 days is late; a late filing is rejected with `ERR_FILING_DEADLINE_PASSED` (HTTP 422). When both conditions pass, the case moves to `ELIGIBLE`, its `eligibility_status` is set to `ELIGIBLE`, and a `Notification` is written with `event_type` `ELIGIBILITY_DECISION` on the `VINE` channel.

Alternatively, an `Adjudicator` may rule a case ineligible (`UNDER_REVIEW → INELIGIBLE`); this transition carries no precondition. Ruling a case ineligible sets `eligibility_status` to `INELIGIBLE`, stamps `denied_at` with the current logical clock, records the acting `X-User-ID` as `denied_by_user_id`, and writes a `Notification` with `event_type` `ELIGIBILITY_DECISION` on the `VINE` channel. An ineligible case is not necessarily final — it may be reopened through the appeal cascade of §3.9, which is the only path that takes a case `INELIGIBLE → UNDER_REVIEW`.

Finally, an `Adjudicator` may close an eligible case (`ELIGIBLE → CLOSED`), but only when every `Award` for the case is `FINALIZED` with `payment_status` `FULLY_PAID`, or the case has no award at all; otherwise the close is rejected with `ERR_INVALID_STATE`. A case that concerns a survivor may be tracked through VINE notifications, retrievable per case.

### 3.3. Filing Claims and Provisional Assessment

Against an intake case, an `IntakeCounselor` files one or more `Claim` records, each naming the owning `case_id` and a benefit `category` — one of `MEDICAL`, `LOST_WAGE`, `FUNERAL`, or `MENTAL_HEALTH`. For medical, funeral, and mental-health claims, the counselor supplies a `claimed_amount_cents`. A lost-wage claim is computed rather than claimed as a lump sum, so instead it carries a `weekly_wage_cents` (gross weekly wage), a `num_weeks` count of full weeks of wage loss, a `disability_start_date` marking the inclusive start of the wage-loss period, and a `disability_end_date` marking its **exclusive** end — the period is the half-open interval from start up to but not including end. A new claim begins in `status` `DRAFT`, with its `verified_amount_cents`, `assessed_base_cents`, `collateral_offset_cents`, and `net_claim_cents` all `null` until they are first computed (the latter three at submission, `verified_amount_cents` at approval).

When an `IntakeCounselor` submits a claim (`DRAFT → SUBMITTED`), the system first checks that the required inputs for the claim's category are present: a lost-wage claim must carry `weekly_wage_cents`, `num_weeks`, `disability_start_date`, and `disability_end_date`, while a claim of any other category must carry `claimed_amount_cents`; a missing required input is rejected with `ERR_VALIDATION`. For a lost-wage claim, the system additionally checks that its disability period does not overlap any other non-`DENIED` lost-wage claim on the same case; overlap is judged on the half-open interval, so two periods that merely touch at an endpoint (one ending exactly where the next begins) do not overlap, whereas any shared interior instant does. An overlap is rejected with `ERR_WAGE_PERIOD_OVERLAP` (HTTP 409).

On a successful submission, the claim's assessed base and provisional net are computed. The **assessed base** (`assessed_base_cents`) is the category's raw benefit before any collateral offset. For a lost-wage claim it is derived from the wage: the weekly benefit equals the gross weekly wage multiplied by the wage-replacement rate of 0.6667, capped at a weekly maximum of 120000 cents (that is, $1,200.00 per week), and this weekly benefit is rounded to a whole number of cents using round-half-up **before** it is multiplied by the number of weeks — rounding per week and then multiplying, never the reverse. For a claim of any other category, the provisional assessed base is simply the `claimed_amount_cents`. The system then computes the collateral offset and the provisional net. The **collateral offset** (`collateral_offset_cents`) is the sum of `amount_cents` over the claim's collateral sources whose status is counted for the current variant; at submission time (the provisional variant) both `DECLARED` and `CONFIRMED` collateral sources are counted. The **net claim** (`net_claim_cents`) is the assessed base minus that offset, floored at 0 so it can never go negative.

### 3.4. Declaring and Confirming Collateral Sources

Because a public compensation fund pays only what other sources do not, each `Claim` may have `CollateralSource` records declared against it by an `IntakeCounselor`. A collateral source names the `claim_id` it offsets, a `source_type` (one of `HEALTH_INSURANCE`, `AUTO_INSURANCE`, `LIFE_INSURANCE`, `EMPLOYER_BENEFIT`, `RESTITUTION`, or `OTHER_PUBLIC`), the `amount_cents` that source is expected to pay, and an optional coverage window given by `coverage_start_date` (inclusive) and `coverage_end_date` (inclusive) — a closed interval. The claim referenced by `claim_id` must exist and the declaration must be properly scoped to it; a mismatch is `ERR_REFERENCE_MISMATCH`. A declared source begins in `status` `DECLARED`.

An `Adjudicator` verifies collateral. Confirming a source (`DECLARED → CONFIRMED`) is permitted only when no other already-`CONFIRMED` collateral source of the **same** `source_type` on the same claim has a closed coverage interval that overlaps this one; because both intervals are closed, sources that share even a single boundary date are considered overlapping. A conflicting confirmation is rejected with `ERR_COLLATERAL_PERIOD_OVERLAP` (HTTP 409). Alternatively the adjudicator may waive a source (`DECLARED → WAIVED`), which carries no precondition. Both `CONFIRMED` and `WAIVED` are terminal states for a collateral source. The distinction matters at final assessment: a waived source is treated as producing no offset, whereas a confirmed source does.

### 3.5. Adjudicating Claims

Once a case has reached review, an `Adjudicator` moves each claim `SUBMITTED → UNDER_REVIEW`, and from there to one of two outcomes. Approving a claim (`UNDER_REVIEW → APPROVED`) requires that the parent `VictimCase` be in `status` `ELIGIBLE`; if the case is not eligible, the approval is rejected with `ERR_CASE_NOT_ELIGIBLE` (HTTP 409). For a claim that is not a lost-wage claim, the adjudicator must supply the documented `verified_amount_cents` at this transition; if it is absent, the approval is rejected with `ERR_VALIDATION`. Approval recomputes the claim's figures under the **final** variant. In the final variant, a non-lost-wage claim's assessed base is taken from `verified_amount_cents` rather than the originally claimed figure, while a lost-wage claim's assessed base is recomputed from the same wage formula described in §3.3. The collateral offset is likewise recomputed, but under the final variant **only** `CONFIRMED` collateral sources are counted — `DECLARED` and `WAIVED` sources are excluded — and the net claim is again the assessed base minus that offset, floored at 0.

Alternatively, the adjudicator may deny a claim (`UNDER_REVIEW → DENIED`); denial has no precondition. Denying a claim sets its `net_claim_cents` to 0, stamps `denied_at` with the current logical clock, records the acting `X-User-ID` as `denied_by_user_id`, and writes a `Notification` with `event_type` `CLAIM_DECISION` on the `EMAIL` channel. A denied claim is not permanently closed: when the parent case is reopened by a granted appeal, each of the case's `DENIED` claims is carried back to `UNDER_REVIEW` and its `denied_at` and `denied_by_user_id` are cleared, as described in §3.9.

### 3.6. Calculating an Award and Committing Budget

When a case's claims have been adjudicated, an `Adjudicator` calculates an `Award` for the case, providing the `case_id` and the `expected_program_version` optimistic-concurrency token described in §2.8. The case's parent program must not be `CLOSED` (`ERR_PROGRAM_CLOSED`), the case itself must be `ELIGIBLE` (`ERR_CASE_NOT_ELIGIBLE`), and `expected_program_version` must match the program's current `version` (`ERR_STALE_VERSION`, HTTP 412).

The award figure is built from the case's `APPROVED` claims only; claims still in `DRAFT`, `SUBMITTED`, `UNDER_REVIEW`, or `DENIED` contribute nothing. For each of the four categories, the system sums the `net_claim_cents` of that case's approved claims in the category, then caps that per-category total at the program's matching cap — `medical_cap_cents`, `lost_wage_cap_cents`, `funeral_cap_cents`, or `mental_health_cap_cents`, taking the smaller of the total and the cap. The `gross_award_cents` is the sum of these four capped per-category subtotals. The award's `collateral_offset_cents` is the sum of the `collateral_offset_cents` already recorded on the case's approved claims. The `net_award_cents` is the gross award capped a second time at the program's `overall_case_cap_cents` — the smaller of the gross award and the overall case cap — and floored at 0. This is a nested cap: each category is limited first, then the whole award is limited by the per-case ceiling.

Creating the award must respect the fund. The award's `net_award_cents` added to the program's current `budget_committed_cents` may not exceed the program's `total_budget_cents`; the boundary is allowed (a sum exactly equal to the total budget is fine) and only a strict excess is rejected, with `ERR_BUDGET_EXCEEDED` (HTTP 422). On a successful create, the award records its computed figures, its `approval_status` is `CALCULATED`, its `payment_status` is `UNPAID`, its `amount_paid_cents` is 0, the program's `budget_committed_cents` rises by the new `net_award_cents`, and the program's `version` increments by one — which is exactly what makes a competing client's `expected_program_version` go stale.

An award carries two independent axes. On the **approval axis**, an `Adjudicator` approves a calculated award (`CALCULATED → APPROVED`), which is permitted only when `net_award_cents` is greater than 0; an award with nothing eligible to pay is rejected with `ERR_NO_ELIGIBLE_CLAIMS` (HTTP 422). Approval sets `approval_status` to `APPROVED` and writes a `Notification` with `event_type` `CLAIM_DECISION` on the `LETTER` channel. A `FinanceOfficer` then finalizes an approved award (`APPROVED → FINALIZED`), which carries no precondition and sets `approval_status` to `FINALIZED`. The **payment axis** (`payment_status`) is derived from disbursements and is described in §3.7.

### 3.7. Disbursing an Award

A `FinanceOfficer` schedules a `Disbursement` against an award, providing the `award_id`, a `payee_type` (one of `VICTIM`, `MEDICAL_PROVIDER`, `FUNERAL_HOME`, or `MENTAL_HEALTH_PROVIDER`), the `amount_cents` to pay (which must be strictly greater than 0), and a `pay_run_date`. Two conditions gate scheduling. First, the parent award's `approval_status` must be `APPROVED` or `FINALIZED`; scheduling against a merely calculated award is rejected with `ERR_AWARD_NOT_APPROVED` (HTTP 409). Second, the new amount together with the amounts of the award's existing disbursements that are in `SCHEDULED` or `PAID` status may not exceed the award's `net_award_cents`; an over-scheduling is rejected with `ERR_DISBURSEMENT_EXCEEDS_AWARD` (HTTP 422). A new disbursement begins in `status` `SCHEDULED`.

The `FinanceOfficer` drives the disbursement lifecycle. Marking a disbursement paid (`SCHEDULED → PAID`) again requires the parent award to be `APPROVED` or `FINALIZED` (`ERR_AWARD_NOT_APPROVED`). Payment cascades: the program's `budget_disbursed_cents` increases by the disbursement's `amount_cents`, the award's `amount_paid_cents` is recomputed as the sum of its `PAID` disbursements, the award's `payment_status` is re-derived, and a `Notification` with `event_type` `PAYMENT` on the `VINE` channel is written. The `payment_status` derivation compares `amount_paid_cents` to `net_award_cents`: nothing paid leaves it `UNPAID`, a positive amount below the net award makes it `PARTIALLY_PAID`, and an amount at or above the net award makes it `FULLY_PAID`. A scheduled disbursement may instead be voided (`SCHEDULED → VOID`) with no side effect on the ledger. A paid disbursement may later be clawed back (`PAID → CLAWED_BACK`): the program's `budget_disbursed_cents` is decreased by the `amount_cents`, and the award's `amount_paid_cents` and `payment_status` are recomputed — which may revert the award from `FULLY_PAID` back to `PARTIALLY_PAID` if the paid total drops below the net award. The payment axis is thus fully re-derived from the currently-paid disbursements on every disbursement mutation. `VOID` and `CLAWED_BACK` are terminal for a disbursement.

### 3.8. Restitution Recovery and Subrogation

When an offender is ordered to pay restitution, the program subrogates the case's award and pursues recovery. A `RecoveryOfficer` opens a `RestitutionRecovery` for a case, supplying the `case_id`, the `offender_name` ordered to pay, and the `ordered_amount_cents` of the court order (at least 0). A new recovery begins in `status` `ORDERED` with `recovered_amount_cents` at 0. The officer moves the recovery `ORDERED → COLLECTING` when active collection begins. A recovery may be marked satisfied (`COLLECTING → SATISFIED`) only when `recovered_amount_cents` is at least `ordered_amount_cents`; a premature satisfaction is rejected with `ERR_INVALID_STATE`. A recovery may also be written off (`ORDERED → WRITTEN_OFF` or `COLLECTING → WRITTEN_OFF`) with no precondition. `SATISFIED` and `WRITTEN_OFF` are terminal.

As money arrives, the `RecoveryOfficer` records a `RecoveryReceipt` against a recovery. Each receipt is scoped to its owning recovery through the path, carries the `recovery_id` of that recovery, an `amount_cents` strictly greater than 0, and the `received_date` on which payment was received. A new receipt begins in `status` `RECORDED`; recording it raises the recovery's `recovered_amount_cents` by the receipt amount and raises the program's `budget_recovered_cents` by the same amount. The recovery's `recovered_amount_cents` is at all times the sum of `amount_cents` over its receipts in `RECORDED` status; voided receipts are excluded. A receipt may be voided (`RECORDED → VOID`) by the `RecoveryOfficer`, which recomputes the parent recovery's `recovered_amount_cents` (now excluding the voided receipt) and decreases the program's `budget_recovered_cents` by the voided amount, conserving the recovered figure. `VOID` is terminal for a receipt.

### 3.9. Appeals and the Reopen Cascade

A denied determination may be appealed. An `IntakeCounselor` files an `Appeal`, supplying the `case_id` whose determination is contested, an optional `claim_id` identifying a specific denied claim under appeal, and a free-text `appeal_reason`. When a `claim_id` is given, that claim must belong to the named `case_id`, or the filing is rejected with `ERR_REFERENCE_MISMATCH`. The appeal must be timely: taking the `denied_at` of the target — the specific claim's `denied_at` when a `claim_id` is supplied, otherwise the case's `denied_at` — the number of whole days from that stamp to the current logical clock may not exceed the appeal window of 30 days; the boundary is open, so day 30 is still within the window and day 31 has expired. An expired appeal is rejected with `ERR_APPEAL_WINDOW_EXPIRED` (HTTP 422). A filed appeal begins in `status` `FILED` with `filed_at` stamped from the logical clock.

An `AppealsOfficer` reviews the appeal (`FILED → UNDER_REVIEW`) and then decides it. Both deciding transitions are subject to the segregation-of-duties rule of §2.10: the acting `X-User-ID` must differ from the `denied_by_user_id` recorded on the appeal's target, or the decision is rejected with `ERR_SEGREGATION_OF_DUTIES`. Denying an appeal (`UNDER_REVIEW → DENIED`) records the acting `X-User-ID` as `decided_by_user_id` and writes a `Notification` with `event_type` `APPEAL_DECISION` on the `LETTER` channel.

Granting an appeal (`UNDER_REVIEW → GRANTED`) records `decided_by_user_id` and triggers a cascading reopen. The target `VictimCase` is carried `INELIGIBLE → UNDER_REVIEW`: its `eligibility_status` is reset to `UNDETERMINED` and its `denied_at` is cleared. That reopen in turn cascades to each of the case's claims that sits in `DENIED`, carrying every such claim `DENIED → UNDER_REVIEW` and clearing that claim's `denied_at` and `denied_by_user_id`. Finally a `Notification` with `event_type` `CASE_REOPENED` on the `VINE` channel is written for the case, and the appeal decision itself is recorded through a `Notification` with `event_type` `APPEAL_DECISION` on the `VINE` channel. This is the sole mechanism by which a case leaves `INELIGIBLE`, and the sole mechanism by which a claim leaves `DENIED`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that transition or otherwise modify an existing resource return `200 OK`. Reads return `200 OK`. Request bodies, response bodies, and side effects for each endpoint are specified by the workflows in §3, not repeated here.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/compensation/programs` | Create a compensation program/fund | ProgramAdmin |
| GET | `/compensation/programs/{id}` | Get a program | Any role |
| GET | `/compensation/programs` | List programs (paginated); filter by status | Any role |
| POST | `/compensation/programs/{id}/transition` | Transition a program (OPEN→CLOSED) | ProgramAdmin |
| POST | `/compensation/cases` | Create a victim case (intake) | IntakeCounselor |
| GET | `/compensation/cases/{id}` | Get a case | Any role |
| GET | `/compensation/cases` | List cases; filter by program_id or status | Any role |
| POST | `/compensation/cases/{id}/transition` | Transition a case (submit/review/determine/close) | IntakeCounselor, Adjudicator |
| GET | `/compensation/cases/{id}/notifications` | List notifications for a case | Any role |
| POST | `/compensation/claims` | Create a claim under a case | IntakeCounselor |
| GET | `/compensation/claims/{id}` | Get a claim | Any role |
| GET | `/compensation/claims` | List claims; filter by case_id, category, status | Any role |
| POST | `/compensation/claims/{id}/transition` | Transition a claim (submit/review/approve/deny) | IntakeCounselor, Adjudicator |
| POST | `/compensation/collateral-sources` | Declare a collateral source against a claim | IntakeCounselor |
| GET | `/compensation/collateral-sources/{id}` | Get a collateral source | Any role |
| GET | `/compensation/collateral-sources` | List collateral sources; filter by claim_id or status | Any role |
| POST | `/compensation/collateral-sources/{id}/transition` | Confirm or waive a collateral source | Adjudicator |
| POST | `/compensation/awards` | Create (calculate) an award for a case | Adjudicator |
| GET | `/compensation/awards/{id}` | Get an award | Any role |
| GET | `/compensation/awards` | List awards; filter by case_id | Any role |
| POST | `/compensation/awards/{id}/transition` | Transition an award (approve/finalize) | Adjudicator, FinanceOfficer |
| POST | `/compensation/disbursements` | Schedule a disbursement against an award | FinanceOfficer |
| GET | `/compensation/disbursements/{id}` | Get a disbursement | Any role |
| GET | `/compensation/disbursements` | List disbursements; filter by award_id or status | Any role |
| POST | `/compensation/disbursements/{id}/transition` | Transition a disbursement (pay/void/clawback) | FinanceOfficer |
| POST | `/compensation/recoveries` | Open a restitution recovery for a case | RecoveryOfficer |
| GET | `/compensation/recoveries/{id}` | Get a recovery | Any role |
| GET | `/compensation/recoveries` | List recoveries; filter by case_id or status | Any role |
| POST | `/compensation/recoveries/{id}/transition` | Transition a recovery (collecting/satisfied/written-off) | RecoveryOfficer |
| POST | `/compensation/recoveries/{id}/receipts` | Record a receipt against a recovery | RecoveryOfficer |
| GET | `/compensation/recoveries/{id}/receipts` | List receipts for a recovery; filter by status | Any role |
| POST | `/compensation/receipts/{id}/transition` | Void a receipt | RecoveryOfficer |
| POST | `/compensation/appeals` | File an appeal of a case/claim denial | IntakeCounselor |
| GET | `/compensation/appeals/{id}` | Get an appeal | Any role |
| GET | `/compensation/appeals` | List appeals; filter by case_id, claim_id, or status | Any role |
| POST | `/compensation/appeals/{id}/transition` | Transition an appeal (review/grant/deny) | AppealsOfficer |
| GET | `/compensation/notifications/{id}` | Get a notification | Any role |
| POST | `/compensation/_clock/set_current_utc` | Set the server logical clock | ProgramAdmin |

"Any role" means each of `ProgramAdmin`, `IntakeCounselor`, `Adjudicator`, `FinanceOfficer`, `RecoveryOfficer`, and `AppealsOfficer` is authorized for that read.

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_PROGRAM_NOT_FOUND` | 404 |
| `ERR_CASE_NOT_FOUND` | 404 |
| `ERR_CLAIM_NOT_FOUND` | 404 |
| `ERR_COLLATERAL_SOURCE_NOT_FOUND` | 404 |
| `ERR_AWARD_NOT_FOUND` | 404 |
| `ERR_DISBURSEMENT_NOT_FOUND` | 404 |
| `ERR_RECOVERY_NOT_FOUND` | 404 |
| `ERR_RECEIPT_NOT_FOUND` | 404 |
| `ERR_APPEAL_NOT_FOUND` | 404 |
| `ERR_REFERENCE_MISMATCH` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CASE_NOT_ELIGIBLE` | 409 |
| `ERR_AWARD_NOT_APPROVED` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_PROGRAM_CLOSED` | 409 |
| `ERR_FILING_DEADLINE_PASSED` | 422 |
| `ERR_APPEAL_WINDOW_EXPIRED` | 422 |
| `ERR_ELIGIBILITY_CRITERIA_NOT_MET` | 422 |
| `ERR_WAGE_PERIOD_OVERLAP` | 409 |
| `ERR_COLLATERAL_PERIOD_OVERLAP` | 409 |
| `ERR_NO_ELIGIBLE_CLAIMS` | 422 |
| `ERR_DISBURSEMENT_EXCEEDS_AWARD` | 422 |
| `ERR_BUDGET_EXCEEDED` | 422 |
