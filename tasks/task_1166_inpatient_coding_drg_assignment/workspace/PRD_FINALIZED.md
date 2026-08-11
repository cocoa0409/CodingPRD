# Inpatient Coding & DRG Assignment API — Product Requirements Document

## 1. Introduction

A hospital's Health Information Management (HIM) coding department sits at the chokepoint between clinical documentation and the revenue cycle. Every discharged inpatient account must have a complete chart, an accurately sequenced set of diagnosis and procedure codes, a correctly grouped diagnosis-related group (DRG), and a clean bill — all before the discharged-not-final-billed (DNFB) backlog starts to age. Errors are not merely clerical: a mis-sequenced principal diagnosis or a wrong present-on-admission indicator changes the severity level, the relative weight, and ultimately the expected reimbursement, and payers claw back overpayments through post-payment reviews.

This document specifies an API that runs that department end to end. It covers account registration and chart-deficiency tracking, a credential-gated coding queue with computed priority scores, diagnosis and procedure capture with principal-selection and manifestation-pairing rules, dual-variant DRG grouping with a pinned reimbursement formula, coder productivity and accuracy measurement through pre-bill audits, DNFB backlog sweeps, and a post-payment review and rebilling workflow guarded by segregation of duties. Time inside the system is driven by a controllable logical clock so that aging, timely-filing, and sampling windows behave deterministically.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes five distinct roles: `CodingManager`, `Coder`, `Auditor`, `BillingClerk`, and `ComplianceOfficer`. A request with a missing or unknown `X-User-Role`, or a missing `X-User-ID`, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Access to specific operations is restricted by role; an attempt to perform an action outside of the caller's designated role is rejected with `ERR_FORBIDDEN` (HTTP 403).

The five roles behave as follows:

- A `CodingManager` is the HIM coding manager: they register accounts, manage charts, deficiencies, and coders, run the coding queue and DNFB sweeps, accept or return submitted coding, and operate the logical clock.
- A `Coder` is a credentialed coding specialist who works their own assignments and captures diagnosis and procedure lines on the charts those assignments cover.
- An `Auditor` is a coding auditor — themselves a credentialed coder of rank CCS or higher — who opens pre-bill audits on other coders, records findings, and applies or dismisses them.
- A `BillingClerk` is a billing office clerk who creates and finalizes bills, records payer payments, opens post-payment reviews, and files rebill requests.
- A `ComplianceOfficer` approves or cancels rebill requests and must never be the clerk who requested them.

The identity carried by `X-User-ID` depends on the role. When `X-User-Role` is `Coder`, `X-User-ID` is the `id` of the acting `Coder`; ownership checks on any resource that references a coder — most importantly an assignment's `coder_id` — compare that field to `X-User-ID`. When `X-User-Role` is `Auditor`, `X-User-ID` is likewise the `id` of a persisted `Coder`; the server records it as `auditor_id` on any audit the caller creates and compares it against `subject_coder_id` to enforce the self-audit ban. When `X-User-Role` is `CodingManager`, `BillingClerk`, or `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `requested_by` on a rebill request or `decided_by` on the request's decision — but it never compares these opaque identifiers to any entity's `id`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every resource in this domain — patient accounts, charts, deficiencies, diagnosis and procedure lines, coders, assignments, coded cases, bills, sweeps, audits, findings, reviews, and rebill requests — carries a standard set of system-managed fields:

- **`id` (string):** A unique, system-generated identifier for the resource, formatted as a UUID with no type prefix.
- **`created_at` (string):** An ISO 8601 timestamp in UTC with three fractional digits (e.g., `2026-05-24T10:30:00.123Z`) indicating when the resource was first created.
- **`updated_at` (string):** An ISO 8601 UTC timestamp indicating when the resource was last modified. This field is refreshed upon any change to the resource's properties, including changes made by automatic cascades.
- **`version` (integer):** A system-managed integer that increments with every modification to the resource. This field backs optimistic concurrency control.

No entity in this system is exempt from this convention; all fourteen resource types expose the full set of four fields.

### 2.5. The Logical Clock

Time inside the system is read from a logical clock, never from wall-clock time. Before any clock-setting call is made, the clock reads exactly `2026-05-01T00:00:00Z`. A `CodingManager`-only capability advances the clock to a caller-supplied instant carried in the `to_iso8601` field, after which every subsequent read returns the new instant until it is set again.

All system-assigned timestamps derive from this clock: `assigned_at`, `started_at`, `submitted_at`, and `accepted_at` on assignments, `resolved_at` on deficiencies, `finalized_at` on bills, and `dnfb_flagged_at` on flagged accounts. The clock also anchors queue-priority aging, DNFB sweep aging, and the timely-filing window for rebills.

### 2.6. Reimbursement Arithmetic and Numeric Precision

All monetary amounts in this system are represented as integer numbers of cents; there are no fractional-cent values anywhere in the API. Where a computation produces a fractional cent — the DRG payment, the cost estimate, and the outlier payment in the expected-reimbursement calculation — each such component is individually rounded half up to whole cents first, and the rounded components are then summed. Summing the unrounded components and rounding once at the end is a different, forbidden order.

Several other numeric fields carry their own fixed precision. A coded case's `relative_weight` is stored with exactly four decimal places, precisely as tabled by the grouper variant's weight table. Both audit accuracy scores, `accuracy_code_based` and `accuracy_financial`, are rounded half up to four decimal places. A coder's `productivity_units_per_day` is rounded half up to two decimal places. An assignment's `priority_score` is always an integer and involves no rounding at all. DNFB aging compares exact fractional day counts against the integer day threshold — elapsed time is not rounded before the comparison.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and both reject a client whose view of the guarded resource has gone stale.

Regrouping a coded case requires the request to carry `expected_coded_case_version`, set to the value of the case's `version` the client last observed. If the case's current `version` has advanced beyond that — because another regroup or an audit-finding application has legitimately recomputed the grouping in the meantime — the regroup is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from regrouping a case it has not observed.

Creating a rebill request requires the request to carry `expected_bill_version`, set to the value of the bill's `version` the client last observed. If the bill's current `version` no longer matches — because another writer has moved the bill since, for example by creating a rebill that supersedes the client's plan — the creation is rejected with `ERR_STALE_VERSION` (HTTP 412).

Endpoints other than these two do not take a version field.

### 2.8. Validation Order and Error Precedence

When a request would fail several checks at once, the failure reported is the earliest one on the following fixed ladder, evaluated in this order:

1. **Authentication** — missing or unknown `X-User-Role`, or missing `X-User-ID`, yields `ERR_UNAUTHENTICATED` (HTTP 401).
2. **Authorization** — a role not permitted for the endpoint yields `ERR_FORBIDDEN` (HTTP 403).
3. **Existence** — a referenced resource that does not exist yields its dedicated 404: `ERR_ACCOUNT_NOT_FOUND` for patient accounts, `ERR_CHART_NOT_FOUND` for charts, `ERR_CODER_NOT_FOUND` for coders, `ERR_ASSIGNMENT_NOT_FOUND` for assignments, `ERR_BILL_NOT_FOUND` for bills, `ERR_CODED_CASE_NOT_FOUND` for coded cases, `ERR_AUDIT_NOT_FOUND` for coding audits, `ERR_FINDING_NOT_FOUND` for audit findings, `ERR_REVIEW_NOT_FOUND` for post-payment reviews, and `ERR_REBILL_NOT_FOUND` for rebill requests. A reference to a chart deficiency, diagnosis line, procedure line, or DNFB sweep that does not exist is instead reported as `ERR_INVALID_REQUEST` with HTTP status 404.
4. **State admissibility** — the target resource must be in a state that permits the requested transition; generic state-precondition failures yield `ERR_INVALID_STATE` (HTTP 409). This covers, for example, submitting from `RETURNED`, finalizing from `DRAFT`, resolving an already-`APPLIED` finding, or recording a payment on a `REBILLED` bill. Specific state checks at this tier have their own codes: `ERR_CHART_NOT_READY`, `ERR_CHART_NOT_CODED`, and `ERR_CODER_INACTIVE`.
5. **Optimistic concurrency** — a stale `expected_coded_case_version` or `expected_bill_version` yields `ERR_STALE_VERSION` (HTTP 412), per §2.7.
6. **Business-safety rules** — credential-rank shortfalls (`ERR_CODER_CREDENTIAL_INSUFFICIENT`), self-audit attempts (`ERR_SELF_AUDIT_FORBIDDEN`), a POA indicator of `U` on a CC or MCC line (`ERR_POA_INVALID_FOR_CODE`), and a rebill approver who is also the requester (`ERR_SEGREGATION_OF_DUTIES`).
7. **Business constraints** — malformed or missing input and invalid enum members (`ERR_INVALID_REQUEST`, HTTP 400), and the coding-rule violations `ERR_PRINCIPAL_DX_REQUIRED`, `ERR_INVALID_PRINCIPAL_CODE`, `ERR_DUPLICATE_SEQUENCE`, `ERR_MANIFESTATION_ORDER`, `ERR_ASSIGNMENT_EXISTS`, `ERR_NO_ELIGIBLE_CODER`, and `ERR_CASE_NOT_IN_SAMPLE`. Within this tier the input-validation failures are evaluated before the coding-rule violations, so a request that is both malformed and in breach of a coding rule is reported as `ERR_INVALID_REQUEST`.
8. **Temporal rules** — `ERR_WORKLOAD_OVERLAP`, `ERR_AUDIT_WINDOW_OVERLAP`, and `ERR_TIMELY_FILING_EXPIRED`.
9. **Referential completeness** — `ERR_OPEN_FINDINGS_REMAIN` when an audit still has unresolved findings at completion.
10. **Fiscal equality** — `ERR_REBILL_DELTA_MISMATCH` when a rebill's delta does not equal the review's claimed delta.

Because of this ordering, checks at a lower number mask those at a higher one. A concrete example: when a coder starts an assignment, the credential-rank check (tier 6) is evaluated before the one-assignment-in-progress workload rule (tier 8), so an under-credentialed coder who is also busy sees `ERR_CODER_CREDENTIAL_INSUFFICIENT`, not `ERR_WORKLOAD_OVERLAP`.

Where an endpoint path nests one resource under another — for instance, a post-payment review created under a bill, or a finding created under an audit — path identifiers are validated from left to right, and the first identifier that does not resolve to an existing resource determines the 404 returned.

### 2.9. Ownership and Segregation of Duties

Three rules keep any single operator from controlling both sides of a sensitive decision, and one rule keeps coders inside their own work.

First, coder ownership: diagnosis-line capture and edits, procedure-line capture, and the start and submit actions on an assignment are only available to the `Coder` whose `id` equals that assignment's `coder_id`. A coder touching another coder's assignment or lines is rejected with `ERR_FORBIDDEN`.

Second, audit independence: an auditor may not audit themselves. At audit creation, the caller's `X-User-ID` must differ from the `subject_coder_id`; a self-audit is rejected with `ERR_SELF_AUDIT_FORBIDDEN` (HTTP 403).

Third, rebill segregation of duties: the `ComplianceOfficer` who approves a rebill request must be a different user than the clerk recorded as its `requested_by`. An approver whose `X-User-ID` equals `requested_by` is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

### 2.10. Derived Fields and Immediate Consistency

Several fields are never written by clients directly; the server derives them and keeps them reconciled as events occur. A chart's `open_deficiency_count` tracks how many of its deficiencies remain `OPEN`. A coder's `workload_units`, `accepted_count`, `accepted_weighted_units`, `productivity_units_per_day`, `accuracy_running`, and `credential_review_required` are all maintained by assignment and audit events. A bill's `expected_reimbursement_cents` mirrors its chart's coded case, and its `net_receivable_cents` is derived from billed and paid amounts. An account's `dnfb_flag` and `dnfb_flagged_at` are written only by DNFB sweeps.

The consistency model is immediate: when one operation mutates several resources through a cascade, every one of those mutations is applied atomically and is visible in the response of the same request that triggered it. Each resource touched by a mutation — including one touched only through a cascade — has its `updated_at` refreshed and its `version` incremented.

## 3. Business Logic & Workflows

### 3.1. Registering Accounts and Completing the Chart

A `CodingManager` registers a patient account with its `mrn` (the medical record number, unique across all accounts), the `admit_at` admission timestamp, a `patient_class` of `INPATIENT` or `OBSERVATION`, a `financial_class` of `MEDICARE`, `MEDICAID`, `COMMERCIAL`, or `SELF_PAY`, and `total_charges_cents`, the total posted charges as a non-negative integer number of cents. A new account begins `ADMITTED`; its `discharge_at` and `discharge_disposition` remain unset, and its `dnfb_flag` reads false, until later events say otherwise. The account listing supports filtering by `status`, and a `dnfb_only` flag on the same listing returns just the DNFB backlog in sweep order (see §3.7).

One chart may be opened per account, by a `CodingManager` supplying the `account_id` and an `acuity` of `MEDICAL_LOW`, `MEDICAL_HIGH`, or `SURGICAL`; the acuity drives both the credential requirement for coding the chart and its workload weight. A chart begins `OPEN` with an `open_deficiency_count` of zero. Charts can be listed with `account_id` and `status` filters.

Chart completeness is tracked through deficiencies. Logging a deficiency takes the `chart_id`, a `type` of `MISSING_H_AND_P`, `MISSING_DISCHARGE_SUMMARY`, `MISSING_SIGNATURE`, or `MISSING_OP_REPORT`, and a `due_at` provider-completion deadline; each logged deficiency increments the chart's `open_deficiency_count` and starts life `OPEN`. Resolving a deficiency sets its `resolved_at`, moves it to `RESOLVED`, and decrements the count. Deficiencies can be listed by `chart_id` and `status`.

Discharge and deficiency resolution interlock to decide when a chart is ready. Discharging an account records `discharge_at` — which must be strictly later than `admit_at`, with violations rejected as invalid requests — together with a `discharge_disposition` of `HOME`, `SNF`, `REHAB`, `EXPIRED`, or `AMA`, moving the account from `ADMITTED` to `DISCHARGED`. The chart advances from `OPEN` to `READY_FOR_CODING` only when both conditions hold at once: the account is `DISCHARGED` and the chart's `open_deficiency_count` is zero. In practice that means whichever event happens last performs the advance — a discharge over a clean chart readies it immediately, while a discharge over outstanding deficiencies leaves the chart `OPEN` until a `CodingManager` resolves the last one, at which point the chart readies itself.

### 3.2. The Coding Queue: Assignment, Credential Gating, and Priority

When a chart reaches `READY_FOR_CODING`, a `CodingManager` queues it for coding by creating an assignment carrying the `chart_id` and a `due_at` coding deadline, optionally naming a `coder_id`. Two guards fire first: the chart must actually be `READY_FOR_CODING` (otherwise `ERR_CHART_NOT_READY`), and the chart may have at most one non-terminal assignment — that is, one in `QUEUED`, `ASSIGNED`, `IN_PROGRESS`, `SUBMITTED`, or `RETURNED` — with a second attempt rejected as `ERR_ASSIGNMENT_EXISTS`.

Credential ranks order the coding workforce: `CCA` is rank 1, `CCS` rank 2, `RHIT` rank 3, and `RHIA` rank 4. A chart's acuity sets its minimum credential: `MEDICAL_LOW` requires at least `CCA`, `MEDICAL_HIGH` requires at least `CCS`, and `SURGICAL` requires at least `RHIT`. Naming an under-credentialed coder at queue time is rejected with `ERR_CODER_CREDENTIAL_INSUFFICIENT`. If `coder_id` is omitted, the system auto-selects from the pool of `ACTIVE` coders who meet the chart's credential requirement, ranking candidates by their current `workload_units` ascending and breaking ties by the coder's `created_at` ascending; an empty pool yields `ERR_NO_ELIGIBLE_CODER`.

A new assignment starts life `ASSIGNED`, with the coder attached and `assigned_at` stamped from the logical clock. Creation debits the assigned coder's `workload_units` by the chart's acuity weight — one unit for `MEDICAL_LOW`, two for `MEDICAL_HIGH`, three for `SURGICAL` — and computes the assignment's `priority_score`.

The priority score blends four components. Let the whole days since discharge be the elapsed time between the account's `discharge_at` and the logical clock, truncated down to whole days. The aging tier contributes 10 points when the account was discharged two days ago or less, 40 points for three to five days, 70 points for six to ten days, and 100 points once eleven days or more have elapsed. The charge component adds one point per whole 100000-cent block of the account's `total_charges_cents`, capped at 30 points. Acuity contributes 0 points for `MEDICAL_LOW`, 10 for `MEDICAL_HIGH`, and 20 for `SURGICAL`. Finally, an account whose `dnfb_flag` is set adds 25 points. The `priority_score` is the sum of these four components, capped at 150, and is always an integer. Because a chart can only become `READY_FOR_CODING` after discharge, the days-since-discharge figure is always well-defined when the score is first computed; the score is computed at creation and later recomputed by DNFB sweeps (§3.7). The queue can be browsed through the assignment listing, filterable by `chart_id`, `coder_id`, and `status`.

A manager may rebalance the queue after creation. Assigning a `QUEUED` assignment to a named coder re-checks that coder's credential rank against the chart requirement (`ERR_CODER_CREDENTIAL_INSUFFICIENT` on a shortfall), stamps `assigned_at`, and debits the coder's `workload_units` by the acuity weight, moving the assignment from `QUEUED` to `ASSIGNED`. Releasing an `ASSIGNED` assignment performs the compensating action: the coder's `workload_units` is credited back by the same weight, the assignment's `coder_id` is cleared to null, and the assignment returns to `QUEUED`.

### 3.3. Starting Work and Capturing Diagnoses and Procedures

A coder starts work on an assignment that is `ASSIGNED` — or `RETURNED` after a rework cycle — moving it to `IN_PROGRESS`. The caller must be the assignment's own coder (anyone else is refused with `ERR_FORBIDDEN`), the coder must be `ACTIVE` (`ERR_CODER_INACTIVE` otherwise), and the credential-rank check is applied again (`ERR_CODER_CREDENTIAL_INSUFFICIENT`). A coder may hold at most one `IN_PROGRESS` assignment — an aggregate capacity of one — so starting while another assignment is already in progress is rejected with `ERR_WORKLOAD_OVERLAP`; as noted in §2.8, the credential check is evaluated before this workload rule. Starting stamps `started_at` from the clock, and the first start on a chart moves the chart from `READY_FOR_CODING` to `IN_CODING`. On a rework re-entry from `RETURNED`, the chart is already `IN_CODING`, so no chart transition occurs.

While the chart is `IN_CODING`, the assigned coder captures diagnosis lines, each carrying the `chart_id`, an `icd_code` (an ICD-10-CM code), a present-on-admission indicator `poa` of `Y`, `N`, `U`, `W`, or `EXEMPT`, and a `sequence` — an integer of at least 1 that must be unique among the chart's `ACTIVE` lines, with duplicates refused at creation time by `ERR_DUPLICATE_SEQUENCE`. A line may be marked `is_principal` (defaulting to false); codes starting with `R` or `Z` are symptom or external-cause codes and may never serve as the principal diagnosis. Each line also carries a `cc_level` of `NONE` (the default), `CC`, or `MCC` describing its complication/comorbidity weight. A `poa` of `U` is forbidden on any line whose `cc_level` is `CC` or `MCC` — documentation "unable to determine" cannot support a severity-raising condition — and such a line is rejected with `ERR_POA_INVALID_FOR_CODE`, both at capture and on later edits. Etiology/manifestation pairs are expressed by setting `is_manifestation` (default false) and pointing `manifestation_of_id` at the etiology line on the same chart; the reference is required whenever `is_manifestation` is true, and its omission is an invalid request.

Existing lines can be edited — `poa`, `sequence`, `is_principal`, and `cc_level` may all be patched, with the POA and sequence rules above re-applied — or voided by patching `status` to `VOID`. Both kinds of edit are permitted only while the chart is `IN_CODING` and only by the coder who holds the chart's `IN_PROGRESS` or `RETURNED` assignment; a line on a chart in any other state refuses the edit as `ERR_INVALID_STATE`. Diagnosis lines may be listed with `chart_id`, `status`, and `manifestation_of_id` filters, the last of which enumerates the manifestations hanging off a given etiology line.

Procedure capture is simpler: a procedure line carries the `chart_id`, a `pcs_code` (an ICD-10-PCS code), an `is_or` flag (default false) marking operating-room procedures, and a `performed_at` timestamp, and may be added while the chart is `IN_CODING`. The flag matters downstream: any `ACTIVE` procedure line with `is_or` set places the whole case in the surgical partition at grouping time. Procedure lines can be listed by `chart_id`.

### 3.4. Submission, DRG Grouping, and Expected Reimbursement

Submitting is the coder's declaration that the chart is fully coded, and it is the moment the sequencing rules bite. The submit action on an `IN_PROGRESS` assignment — again restricted to the assignment's own coder — enforces four checks: exactly one `ACTIVE` diagnosis line must carry `is_principal` (`ERR_PRINCIPAL_DX_REQUIRED` otherwise); that principal line's `icd_code` must not start with `R` or `Z` (`ERR_INVALID_PRINCIPAL_CODE`); sequence numbers must still be unique among `ACTIVE` lines, re-checked here (`ERR_DUPLICATE_SEQUENCE`); and every `ACTIVE` manifestation line must be sequenced strictly after its etiology line, so a manifestation whose `sequence` is less than or equal to its etiology's fails with `ERR_MANIFESTATION_ORDER`.

A successful submission moves the chart from `IN_CODING` to `SUBMITTED`, stamps `submitted_at`, and creates exactly one coded case per chart. The case is born `GROUPED` with `grouper_variant` `MS_DRG`, its `principal_dx_id` pointing at the chart's single `ACTIVE` principal line. Because submission returns the assignment rather than the case, the freshly created case is discovered through the coded-case listing, which filters by `chart_id` and `principal_dx_id`.

Grouping proceeds as follows. The `base_partition` is `SURGICAL` when any `ACTIVE` procedure line on the chart has `is_or` set, and `MEDICAL` otherwise. The eligible secondary diagnoses are the chart's `ACTIVE` lines that are not the principal, whose `cc_level` is not `NONE`, and whose `poa` is not `N` — a condition that arose after admission is a hospital-acquired condition and never raises severity. Under the `MS_DRG` variant, the `severity_level` is the single highest eligible level: `WITH_MCC` if any eligible line is an MCC, else `WITH_CC` if any eligible line is a CC, else `WITHOUT_CC_MCC`; counts of CC and MCC lines do not accumulate. The `relative_weight` is then read from the MS weight table: 1.0000 for `WITHOUT_CC_MCC`, 1.4000 for `WITH_CC`, and 2.1000 for `WITH_MCC`. Under the `AP_DRG` variant, severity instead accumulates severity-of-illness points — two points per eligible MCC line plus one point per eligible CC line — and the `severity_level` is `SOI_4` when the total is at least four points, `SOI_3` at exactly three, `SOI_2` at one or two, and `SOI_1` at zero; the AP weight table gives 0.9000 for `SOI_1`, 1.2000 for `SOI_2`, 1.8000 for `SOI_3`, and 2.5000 for `SOI_4`. Identical line data therefore yields a different severity, weight, and expected reimbursement under the two variants.

The expected reimbursement follows immediately after grouping, at submission, at every regroup, and at every applied audit finding. The DRG payment component is the product of a base rate of 650000 cents and the case's just-computed `relative_weight`, rounded half up to whole cents. The cost estimate is thirty percent of the account's `total_charges_cents`, likewise rounded half up to whole cents. The outlier threshold is the rounded DRG payment plus a fixed-loss amount of 500000 cents. The outlier payment is eighty percent of the amount by which the rounded cost estimate exceeds that threshold — zero when the estimate does not exceed it — rounded half up to whole cents. The case's `expected_reimbursement_cents` is the sum of the rounded DRG payment and the rounded outlier payment; per §2.6, rounding each component to whole cents before summing is the pinned order, and rounding only the final sum is forbidden.

A `CodingManager` or an `Auditor` may regroup a case that is still `GROUPED`, optionally switching its `grouper_variant` between `MS_DRG` and `AP_DRG`. Regrouping is OCC-guarded per §2.7: the request must carry `expected_coded_case_version` matching the case's current `version`, and a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412). A successful regroup recomputes `severity_level`, `relative_weight`, and `expected_reimbursement_cents` from the chart's current `ACTIVE` lines, increments the case's `version` by one, and — while the account's bill exists in `DRAFT` or `READY` — refreshes the bill's `expected_reimbursement_cents` to the new value. Once the bill has been finalized the case is `LOCKED`, and no further regrouping is possible.

### 3.5. Acceptance, Rework, and Coder Productivity

Acceptance is the terminal act of the coding workflow and belongs to the `CodingManager`. Accepting a `SUBMITTED` assignment moves it to `ACCEPTED` and fires a two-hop cascade: the chart moves from `SUBMITTED` to `CODED`, and if a bill already exists for the account in `DRAFT`, that bill moves to `READY` with its `expected_reimbursement_cents` set to the coded case's current value. The same event settles the coder's books: the coder's `workload_units` is credited back by the chart's acuity weight, `accepted_count` increases by one, `accepted_weighted_units` grows by the same acuity weight, and the coder's `productivity_units_per_day` is recomputed. The assignment's `accepted_at` is stamped from the clock and later serves as the sampling anchor for audits (§3.8).

A manager who is unsatisfied instead returns the work. Returning requires a non-empty `return_reason`; it moves the assignment from `SUBMITTED` to `RETURNED`, pushes the chart back from `SUBMITTED` to `IN_CODING`, and increments the assignment's `returned_count`. The same coder then re-enters through the start action — `RETURNED` to `IN_PROGRESS` under the same caller, credential, and capacity checks as a first start — edits lines while the chart is `IN_CODING`, and submits again. The rework loop may repeat as often as needed.

Coders themselves are managed by the `CodingManager`. Onboarding records an `employee_no` (unique), a `full_name`, and a `credential` of `CCA`, `CCS`, `RHIT`, or `RHIA`; a coder starts `ACTIVE`, and the manager may patch `status` between `ACTIVE` and `INACTIVE` or update `credential` at any time. Fetching a coder reports the full derived profile: `workload_units` is the sum of acuity weights — one for `MEDICAL_LOW`, two for `MEDICAL_HIGH`, three for `SURGICAL` — over the coder's `ASSIGNED` and `IN_PROGRESS` assignments; `accepted_weighted_units` sums the same weights over `ACCEPTED` assignments; and `productivity_units_per_day` is `accepted_weighted_units` divided by a 30-day productivity basis, rounded half up to two decimal places. The remaining two derived fields come from audits: `accuracy_running` holds the `accuracy_code_based` of the coder's most recently `COMPLETED` audit and stays null until that first audit completes, while `credential_review_required` is set true when a completed audit's code-based accuracy falls strictly below 0.9500 and is cleared back to false once a completed audit reaches at least 0.9500.

### 3.6. Billing: From Draft Bill to Recorded Payment

Billing begins when a `BillingClerk` creates the account's bill — one bill per account — by naming the `account_id`. If the chart is already `CODED` at creation, the bill is born `READY` with its `expected_reimbursement_cents` mirroring the coded case; otherwise it begins `DRAFT` and waits for the acceptance cascade (§3.5) to advance it to `READY`. In either state the bill's `expected_reimbursement_cents` continues to track the case: it is refreshed on entry to `READY` and on every regroup or applied audit finding that occurs while the bill is still `DRAFT` or `READY`. Bills may be listed by `account_id` and `status`.

Finalizing a `READY` bill requires the chart to be `CODED` — finalizing against an uncoded chart fails with `ERR_CHART_NOT_CODED`. Finalization copies the current `expected_reimbursement_cents` into `billed_amount_cents`, which is immutable from that moment on, stamps `finalized_at` from the clock, and locks the coded case from `GROUPED` to `LOCKED`, cutting off any further regrouping.

When the payer remits, the clerk records the payment by supplying `paid_amount_cents` and `paid_at`, moving the bill from `FINAL_BILLED` to `PAID`. The bill's `net_receivable_cents` is then derived as `billed_amount_cents` minus `paid_amount_cents`. The `paid_at` timestamp also anchors the timely-filing window that governs any later rebill: a rebill must be created no later than 120 days after `paid_at` (§3.9).

### 3.7. DNFB Backlog Sweeps

Discharged-not-final-billed accounts are the revenue cycle's silent leak, and the sweep is how the department finds them. A `CodingManager` runs a sweep with an optional `threshold_days` (defaulting to 3) and an optional `as_of` reference instant (defaulting to the logical clock). The candidate pool is every `DISCHARGED` account whose bill is either absent entirely or still in `DRAFT` or `READY` — accounts with bills that have reached `FINAL_BILLED` or beyond are not candidates. Each candidate's age is the exact, fractional number of days between its `discharge_at` and the sweep's `as_of`; the account is flagged when that age is at least `threshold_days`, and an age landing exactly on the threshold is flagged.

For every account newly flagged, the sweep sets `dnfb_flag` true and records the sweep's `as_of` in `dnfb_flagged_at`. The sweep resource itself captures the outcome: `flagged_count` counts the newly flagged accounts; `flagged_account_ids` lists them ordered by days since discharge descending, with ties broken by the bill's `expected_reimbursement_cents` descending (treated as zero when the account has no bill) and further ties by the account's `created_at` ascending; and `total_outstanding_cents` sums `expected_reimbursement_cents` across the flagged accounts' bills, counting zero for an account with no bill. The sweep also feeds back into the coding queue: every non-terminal assignment sitting on a flagged account's chart has its `priority_score` recomputed under the §3.2 formula, so the 25-point DNFB boost now applies to those charts. The same backlog ordering backs the account listing's `dnfb_only` view described in §3.1.

### 3.8. Pre-Bill Coding Audits and Findings

Audits are the department's quality instrument, and they run before the bill goes out. An `Auditor` opens an audit by naming the `subject_coder_id` whose work is to be sampled, a sampling window from `window_start` (inclusive) to `window_end` (exclusive — the end must be strictly later than the start), and a `sample_size` of at least one; malformed windows or sample sizes are invalid requests. The caller's `X-User-ID` is recorded as the audit's `auditor_id`; the auditor must be an `ACTIVE` coder holding a credential rank of at least `CCS` (insufficient rank is rejected with `ERR_CODER_CREDENTIAL_INSUFFICIENT`) and must differ from the subject (`ERR_SELF_AUDIT_FORBIDDEN`, per §2.9). Sampling windows for the same subject coder may not overlap: because each window includes its start and excludes its end, a new window that begins exactly when an existing window ends is permitted, but any true overlap is rejected with `ERR_AUDIT_WINDOW_OVERLAP`.

Sampling executes synchronously at creation. The audit's `sampled_case_ids` collects the subject's coded cases whose coding was accepted within the window — that is, whose assignment's `accepted_at` falls at or after `window_start` and strictly before `window_end` — ordered by the case's `expected_reimbursement_cents` descending, ties broken by the case's `created_at` ascending, and capped at `sample_size` entries. A new audit is `IN_REVIEW`, and audits can be listed by `auditor_id`, `subject_coder_id`, and `status`.

Against that sample, the auditor records findings. Each finding names a `coded_case_id` — which must belong to the audit's `sampled_case_ids`, with out-of-sample cases refused by `ERR_CASE_NOT_IN_SAMPLE` — and a `finding_type` of `PRINCIPAL_RESEQUENCE`, `POA_CORRECTION`, `CC_MCC_ADDED`, `CC_MCC_REMOVED`, or `PROCEDURE_ADDED`. Corrective findings (`POA_CORRECTION`, `CC_MCC_REMOVED`, `PRINCIPAL_RESEQUENCE`) identify the line being corrected via `target_diagnosis_id`, which is null for the additive types; `corrected_poa` carries the replacement indicator for a POA correction; `corrected_icd_code` carries the new code for a CC/MCC addition or a principal resequence; and `corrected_cc_level` carries the CC level for the corrected or added code. Findings are listed by `audit_id`, `coded_case_id`, `target_diagnosis_id`, and `status`, and each starts `OPEN`.

Resolving a finding takes a `resolution` of `APPLY` or `DISMISS`, and both flavors require the audit to still be `IN_REVIEW`. Applying a finding is additionally a pre-bill instrument only: the bill on the case's account, if one exists, must be `DRAFT` or `READY`, and an apply attempted after the bill has moved on is rejected with `ERR_INVALID_STATE`. An apply then runs a four-hop cascade. First, the correction lands on the chart's lines: the targeted line has its `poa` flipped for a POA correction, is voided for a CC/MCC removal, or has the principal designation reselected per the corrected code for a principal resequence, while additive findings append a new diagnosis line (for `CC_MCC_ADDED`) or procedure line (for `PROCEDURE_ADDED`). Second, the coded case is recomputed from the mutated lines — `severity_level`, `relative_weight`, and `expected_reimbursement_cents` refresh and the case's `version` increments by one. Third, if a bill exists in `DRAFT` or `READY`, its `expected_reimbursement_cents` follows the case's new value. Fourth, the audit's `applied_findings_count` increases by one, and the finding's `delta_reimbursement_cents` records the signed difference between the new and the old expected reimbursement before the finding closes as `APPLIED`. Dismissal is the quiet path: no line, case, bill, or coder is mutated, `delta_reimbursement_cents` is set to zero, and the finding closes as `DISMISSED`.

Completion closes the audit and scores the coder. The complete action belongs to the audit's own auditor and is refused with `ERR_OPEN_FINDINGS_REMAIN` while any finding on the audit is still `OPEN`. On completion, both accuracy variants are computed. The total line count is the number of `ACTIVE` diagnosis and procedure lines across the charts of the sampled cases as they stand at completion time; the incorrect line count is the number of this audit's `APPLIED` findings — `DISMISSED` findings are excluded from both variants. `accuracy_code_based` is one minus the ratio of incorrect lines to total lines, rounded half up to four decimal places; it measures line-count accuracy and ignores dollar impact. For the financial variant, the absolute values of `delta_reimbursement_cents` over the `APPLIED` findings are summed, and that sum is divided by the sum of the sampled cases' `expected_reimbursement_cents` as they stand at completion time, with the ratio capped at one; `accuracy_financial` is one minus the capped ratio, again rounded half up to four decimal places. Identical findings therefore yield a different score under the two variants. Completion then writes the subject coder's profile: `accuracy_running` takes the new `accuracy_code_based`, and `credential_review_required` becomes true exactly when that score is strictly below 0.9500, clearing back to false at 0.9500 or above.

### 3.9. Post-Payment Reviews and Rebilling

Payment is not always the end of the story. When a payer disputes a settled bill, a `BillingClerk` opens a post-payment review on a `PAID` bill, supplying a `payer_ref` external reference and the `claimed_delta_cents` — the signed over- or underpayment the payer claims. Opening the review moves the bill from `PAID` to `POST_PAYMENT_REVIEW` and increments the bill's `version`; the review itself starts `OPEN`. Reviews can be listed by `bill_id` and `status`. If the dispute evaporates, the clerk closes the review with no change: the review moves from `OPEN` to `CLOSED_NO_CHANGE` and the bill returns to `PAID`.

When the dispute stands, the clerk files a rebill. Creating a rebill request names the `review_id` — the review must be `OPEN` — and a signed `delta_cents` that must equal the review's `claimed_delta_cents`, with any disagreement rejected as `ERR_REBILL_DELTA_MISMATCH`. Two further guards apply, in ladder order: the request is OCC-guarded per §2.7, so `expected_bill_version` must match the bill's current `version` or the creation is rejected with `ERR_STALE_VERSION` (HTTP 412); and timely filing requires the logical clock to read no later than 120 days after the bill's `paid_at` — a request landing exactly on the 120-day deadline is permitted, anything later is `ERR_TIMELY_FILING_EXPIRED`. A successful creation produces a `PENDING` rebill request with the clerk's `X-User-ID` recorded as `requested_by`, moves the review from `OPEN` to `CLOSED_REBILL`, moves the bill from `POST_PAYMENT_REVIEW` to `REBILL_REQUIRED`, and increments the bill's `version` once more. Rebill requests can be listed by `review_id` and `status`.

The decision belongs to compliance. A `ComplianceOfficer` approving a `PENDING` rebill must not be the clerk who filed it: an approver whose `X-User-ID` equals the request's `requested_by` is rejected with `ERR_SEGREGATION_OF_DUTIES`, per §2.9. Approval moves the request to `APPROVED` with the officer recorded as `decided_by`, moves the bill from `REBILL_REQUIRED` to its terminal `REBILLED` state, and adjusts the bill's `net_receivable_cents` to `billed_amount_cents` minus `paid_amount_cents` plus the approved `delta_cents`. Cancelling instead moves the request to `CANCELLED`, returns the bill from `REBILL_REQUIRED` to `PAID`, and restores `net_receivable_cents` to `billed_amount_cents` minus `paid_amount_cents` — the invariant being that creating a rebill and then cancelling it leaves the bill's net receivable exactly as it was.

## 4. Endpoint Definitions

Operations that create new, stand-alone resources (a patient account, a chart, a deficiency, a diagnosis or procedure line, a coder, an assignment, a bill, a DNFB sweep, an audit, a finding, a post-payment review, or a rebill request) return a `201 Created` status code. Operations that modify an existing resource or drive a state transition — discharges, resolutions, assignment lifecycle actions, regroups, finalization, payment recording, review closure, finding resolution, audit completion, rebill decisions, coder updates, and the clock-setting capability — return a `200 OK` status code. All list and single-resource fetches return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock | CodingManager |
| POST | `/patient-accounts` | Register an inpatient account (status `ADMITTED`) | CodingManager |
| GET | `/patient-accounts/{id}` | Fetch one account | All roles |
| GET | `/patient-accounts` | List accounts; `dnfb_only` returns the DNFB backlog in sweep order | All roles |
| POST | `/patient-accounts/{id}/discharge` | Discharge the account; may auto-ready its chart | CodingManager |
| POST | `/charts` | Open a coding chart for an account (one per account) | CodingManager |
| GET | `/charts/{id}` | Fetch one chart | All roles |
| GET | `/charts` | List charts | All roles |
| POST | `/deficiencies` | Log a chart deficiency | CodingManager |
| GET | `/deficiencies/{id}` | Fetch one deficiency | All roles |
| GET | `/deficiencies` | List deficiencies | All roles |
| POST | `/deficiencies/{id}/resolve` | Resolve an `OPEN` deficiency; resolving the last one after discharge readies the chart | CodingManager |
| POST | `/diagnosis-lines` | Add a diagnosis line while the chart is `IN_CODING` | Coder |
| GET | `/diagnosis-lines/{id}` | Fetch one diagnosis line | All roles |
| GET | `/diagnosis-lines` | List diagnosis lines | All roles |
| PATCH | `/diagnosis-lines/{id}` | Edit `poa`/`sequence`/`is_principal`/`cc_level` or void the line | Coder |
| POST | `/procedure-lines` | Add a procedure line while the chart is `IN_CODING` | Coder |
| GET | `/procedure-lines/{id}` | Fetch one procedure line | All roles |
| GET | `/procedure-lines` | List procedure lines | All roles |
| POST | `/coders` | Onboard a coder with a credential | CodingManager |
| GET | `/coders/{id}` | Fetch a coder including workload, accuracy, and productivity stats | All roles |
| PATCH | `/coders/{id}` | Update a coder's status and/or credential | CodingManager |
| POST | `/assignments` | Queue a chart for coding; omitting `coder_id` auto-selects an eligible coder | CodingManager |
| GET | `/assignments/{id}` | Fetch one assignment | All roles |
| GET | `/assignments` | List assignments (the coding queue) | All roles |
| POST | `/assignments/{id}/assign` | Assign a `QUEUED` assignment to a coder | CodingManager |
| POST | `/assignments/{id}/start` | Start work (`ASSIGNED` or `RETURNED` to `IN_PROGRESS`) | Coder |
| POST | `/assignments/{id}/submit` | Submit the coded chart; validates sequencing rules and creates the grouped coded case | Coder |
| POST | `/assignments/{id}/accept` | Accept submitted coding; cascades to chart and bill | CodingManager |
| POST | `/assignments/{id}/return` | Return submitted coding for rework | CodingManager |
| POST | `/assignments/{id}/release` | Release an `ASSIGNED` assignment back to the queue | CodingManager |
| GET | `/coded-cases/{id}` | Fetch one coded case | All roles |
| GET | `/coded-cases` | List coded cases (discovery channel for the case created at submit) | All roles |
| POST | `/coded-cases/{id}/regroup` | Recompute grouping, optionally switching variants; OCC-guarded | CodingManager, Auditor |
| POST | `/bills` | Create the account's bill (`READY` immediately if the chart is already `CODED`) | BillingClerk |
| GET | `/bills/{id}` | Fetch one bill | All roles |
| GET | `/bills` | List bills | All roles |
| POST | `/bills/{id}/finalize` | Final-bill a `READY` bill; locks the coded case | BillingClerk |
| POST | `/bills/{id}/record-payment` | Record payer remittance (`FINAL_BILLED` to `PAID`) | BillingClerk |
| POST | `/dnfb-sweeps` | Run a DNFB backlog sweep and recompute queue priorities | CodingManager |
| GET | `/dnfb-sweeps/{id}` | Fetch a sweep result | All roles |
| POST | `/audits` | Open a coding audit on a subject coder; sampling executes synchronously | Auditor |
| GET | `/audits/{id}` | Fetch one audit | All roles |
| GET | `/audits` | List audits | All roles |
| POST | `/audits/{id}/findings` | Record a finding against a sampled coded case | Auditor |
| GET | `/audit-findings/{id}` | Fetch one finding | All roles |
| GET | `/audit-findings` | List findings | All roles |
| POST | `/audit-findings/{id}/resolve` | Apply (correction cascade) or dismiss an `OPEN` finding | Auditor |
| POST | `/audits/{id}/complete` | Complete the audit; computes both accuracy variants and updates the subject coder | Auditor |
| POST | `/bills/{id}/post-payment-reviews` | Open a payer post-payment review on a `PAID` bill | BillingClerk |
| GET | `/post-payment-reviews/{id}` | Fetch one review | All roles |
| GET | `/post-payment-reviews` | List reviews | All roles |
| POST | `/post-payment-reviews/{id}/close` | Close a review with no change; the bill returns to `PAID` | BillingClerk |
| POST | `/rebill-requests` | Create a rebill against an `OPEN` review; OCC-guarded and timely-filing enforced | BillingClerk |
| GET | `/rebill-requests/{id}` | Fetch one rebill request | All roles |
| GET | `/rebill-requests` | List rebill requests | All roles |
| POST | `/rebill-requests/{id}/approve` | Approve a `PENDING` rebill (approver differs from requester); the bill becomes `REBILLED` | ComplianceOfficer |
| POST | `/rebill-requests/{id}/cancel` | Cancel a `PENDING` rebill; the bill returns to `PAID` with net receivable unchanged | ComplianceOfficer |

## 5. Error Code Catalogue

The catalogue below enumerates every error identifier and its HTTP status. The conditions under which each error is raised are specified in §2 and §3 alongside the workflows they guard.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_ACCOUNT_NOT_FOUND` | 404 Not Found |
| `ERR_CHART_NOT_FOUND` | 404 Not Found |
| `ERR_CODER_NOT_FOUND` | 404 Not Found |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_BILL_NOT_FOUND` | 404 Not Found |
| `ERR_CODED_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_AUDIT_NOT_FOUND` | 404 Not Found |
| `ERR_FINDING_NOT_FOUND` | 404 Not Found |
| `ERR_REVIEW_NOT_FOUND` | 404 Not Found |
| `ERR_REBILL_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_CHART_NOT_READY` | 409 Conflict |
| `ERR_CHART_NOT_CODED` | 409 Conflict |
| `ERR_CODER_INACTIVE` | 409 Conflict |
| `ERR_CODER_CREDENTIAL_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_SELF_AUDIT_FORBIDDEN` | 403 Forbidden |
| `ERR_POA_INVALID_FOR_CODE` | 422 Unprocessable Entity |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_PRINCIPAL_DX_REQUIRED` | 422 Unprocessable Entity |
| `ERR_INVALID_PRINCIPAL_CODE` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_SEQUENCE` | 422 Unprocessable Entity |
| `ERR_MANIFESTATION_ORDER` | 422 Unprocessable Entity |
| `ERR_ASSIGNMENT_EXISTS` | 409 Conflict |
| `ERR_NO_ELIGIBLE_CODER` | 422 Unprocessable Entity |
| `ERR_CASE_NOT_IN_SAMPLE` | 422 Unprocessable Entity |
| `ERR_WORKLOAD_OVERLAP` | 409 Conflict |
| `ERR_AUDIT_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_TIMELY_FILING_EXPIRED` | 422 Unprocessable Entity |
| `ERR_OPEN_FINDINGS_REMAIN` | 409 Conflict |
| `ERR_REBILL_DELTA_MISMATCH` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
