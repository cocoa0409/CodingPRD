# HMDA Register API — Product Requirements Document

## 1. Introduction

Every bank that originates residential mortgages in the United States must maintain a Loan/Application Register and file it with its regulator once a year. The register is not a report that a bank writes at year end; it is a living record that accumulates one row per credit decision, field by field, as an application moves from the moment it is received through underwriting to the moment the institution takes an action on it. What makes the obligation hard is not the volume of records but the number of independent accuracy regimes layered on top of them: fields become required only once certain other fields are known, demographic information must be collected through a channel-dependent procedure, every property must be resolved to a census tract, and the whole register must survive a battery of automated edit checks before an accountable officer may attest to it. Banks that get this wrong face resubmission cycles, public disclosure errors, and fair lending scrutiny driven by their own data.

This document specifies the HMDA Register API, a compliance platform that carries a reporting institution through the complete annual cycle. The service is mounted under `/hmda`, with a single additional test-driving surface outside that prefix. It models the register record with two independent state dimensions — where the record sits in the field-capture workflow, and how clean the record currently is — because in practice those two questions have different owners and different answers. It models the edit battery as a snapshot-based run whose findings can be verified by an analyst but whose validity evaporates the moment anyone reopens an underlying record. It models the filing itself as a cycle rather than a line, because regulators reject filings and banks refile them.

The design priority throughout is *reconstructibility*: given the register, the platform must be able to explain how every derived number was produced — why a record counted toward one total and not another, why a tract was suppressed from the public disclosure, why a defect rate came out at one percentage rather than another. Derived values are therefore never guessed and never approximated; each is the output of a pinned, ordered calculation described in this document, and the ordering is part of the specification rather than an implementation detail.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the capacity in which the caller is acting. If either header is absent, or if the value of `X-User-Role` is not one of the six roles defined below, the request is rejected with `ERR_UNAUTHENTICATED` and HTTP 401. This check runs before anything else, including the existence of the resources named in the path.

The six roles are `SystemAdmin`, `InstitutionAdmin`, `LoanOfficer`, `ComplianceAnalyst`, `ComplianceOfficer`, and `Examiner`. A caller whose role is authenticated but who is not among the roles authorised for the endpoint receives `ERR_FORBIDDEN_ROLE` with HTTP 403. The authorised roles for each endpoint are listed in the table in §4.

- `SystemAdmin` is the platform operator: it onboards reporting institutions, loads census reference data, and drives the logical clock. Those three capabilities belong to `SystemAdmin` alone. When `X-User-Role` is `SystemAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server never compares it to any entity's `id`.
- `InstitutionAdmin` is a bank-side administrator of exactly one institution. When `X-User-Role` is `InstitutionAdmin`, `X-User-ID` is the `id` of the acting `Institution`; ownership checks compare the institution being addressed — whether it is named by the path id or by an `institution_id` in the body — to `X-User-ID`. If an `InstitutionAdmin` addresses an institution whose `id` differs from `X-User-ID`, the request is rejected with `ERR_INSTITUTION_SCOPE_VIOLATION` and HTTP 403. This scope check applies to the institution amendment endpoint, to reading a single institution, and to every institution sub-resource listing.
- `LoanOfficer` is the front-line originator who opens register records, captures and amends fields, advances the record through the capture stages, records the action taken, collects applicant demographics, and geocodes the secured property. When `X-User-Role` is `LoanOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- `ComplianceAnalyst` is the second-line reviewer who resolves geocode ambiguity by manual override, runs the edit battery, verifies quality and macro exceptions, reopens locked records, draws and closes audit scrub samples, records audit findings, and computes fair lending disparities. When `X-User-Role` is `ComplianceAnalyst`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server does record it: verifying an edit exception stores the caller's `X-User-ID` on that exception as `verified_by_user_id`, but it is never matched against an entity's `id`.
- `ComplianceOfficer` is the accountable officer who opens a filing submission, attaches an edit run to it, certifies it, files it, and resubmits it after a rejection. When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it on certification as `certified_by_user_id` but does not compare it to any entity's `id`. It does compare it to the `verified_by_user_id` values recorded by analysts — see §2.11.
- `Examiner` is the regulator-side reviewer. It may read everything on the platform and it alone may accept or reject a filed submission. When `X-User-Role` is `Examiner`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity and is not compared to any entity's `id`.

All six roles may read any institution and any register record; the read surface is deliberately wide because compliance work is cross-functional. Write capability is narrow and does not overlap between roles.

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

Every list endpoint accepts two optional query parameters, `limit` and `offset`. When `limit` is omitted it defaults to 10; the smallest accepted value is 1 and the largest is 100. When `offset` is omitted it defaults to 0, and it may not be negative. A `limit` or an `offset` outside these bounds is a malformed request and is rejected with `ERR_INVALID_REQUEST` and HTTP 400 rather than being silently clamped.

Unless the endpoint's own description says otherwise, list results are ordered by `created_at` ascending — oldest first. List responses carry `limit`, `offset`, `total_count`, and `has_more` inside `meta`, where `total_count` is the size of the full filtered result set before the page window is applied and `has_more` is true exactly when records remain beyond the current page. Filter query parameters, where an endpoint offers them, narrow the set before `total_count` is computed.

### 2.4. Common Resource Properties

Every resource the platform stores carries a server-minted `id`, which is a UUID string with no type prefix of any kind, and a `created_at` timestamp recording when the row was written. Timestamps everywhere in this API — `created_at`, `updated_at`, and every domain-specific datetime such as `filing_deadline_at`, `certified_at`, `verified_at`, `filed_at`, or `published_at` — are ISO 8601 in UTC with exactly three fractional-second digits.

Most resources additionally carry `updated_at`, refreshed on every mutation of the row, and `version`, an integer that starts at 1 when the row is created and increments by exactly 1 on each mutation. `Institution`, `Application`, `DemographicEntry`, `GeocodeAssignment`, `EditRun`, `EditException`, `FilingSubmission`, `AuditSample`, `AuditFinding`, and `FairLendingAnalysis` all behave this way.

Two resources are exceptions and must be implemented differently. `CensusTract` rows are immutable reference data: a tract carries only `id` and `created_at`, and has neither `updated_at` nor `version`. `DisclosureStatement` rows are append-only publication artifacts: they likewise carry only `id` and `created_at`, with no `updated_at` and no `version`. Nothing in the system ever mutates a row of either kind.

The `version` counter matters beyond bookkeeping. It is the value clients echo back under optimistic concurrency control (§2.8), and it is bumped by cascades as well as by direct edits — an `Application` whose `stage` was changed by a system cascade has its `version` incremented exactly as though a `LoanOfficer` had changed it directly.

### 2.5. The Logical Clock

The server does not read wall-clock time for any business decision. It maintains a single logical clock which, before any caller sets it, reads exactly `2026-08-01T00:00:00Z`; it never falls back to real time. A `SystemAdmin` may move the clock by supplying a `to_iso8601` instant to the clock-setting capability described in §4. Every subsequent evaluation that depends on "now" reads the new value: the future-date check on an action taken, the `verified_at` stamp on an edit exception, the `certified_at` stamp on a submission, the `filed_at` stamp and the lateness comparison at filing, and the `published_at` stamp on the disclosure statements. Moving the clock backwards is permitted and simply changes what "now" means for subsequent requests.

### 2.6. Path Resolution and Sub-Resource Navigation

Path identifiers are resolved strictly left to right, and the first identifier that fails to resolve determines the response. A request naming an institution that does not exist yields `ERR_INSTITUTION_NOT_FOUND`; an unknown register record yields `ERR_APPLICATION_NOT_FOUND`; and the same pattern holds for `ERR_DEMOGRAPHIC_ENTRY_NOT_FOUND`, `ERR_GEOCODE_ASSIGNMENT_NOT_FOUND`, `ERR_CENSUS_TRACT_NOT_FOUND`, `ERR_EDIT_RUN_NOT_FOUND`, `ERR_EDIT_EXCEPTION_NOT_FOUND`, `ERR_SUBMISSION_NOT_FOUND`, and `ERR_AUDIT_SAMPLE_NOT_FOUND`. All of these carry HTTP 404.

Foreign keys supplied inside a request body are resolved with the same vocabulary but at a later point in the validation ladder (§2.9): an unresolvable `institution_id`, `application_id`, `census_tract_id`, `edit_run_id`, or `audit_sample_id` in a body yields the corresponding not-found error and HTTP 404.

Because no entity in this system is created through a nested path, the sub-resource listings exist purely for navigation in the reverse direction: from an institution to its register records, edit runs, filing submissions, audit samples, and fair lending analyses; from a census tract to the geocode assignments resolved onto it; from a register record to the corrections that supersede it, to its applicant demographic rows, to its geocode attempts, to every edit exception ever raised against it, and to the scrub findings that name it; from an edit run to its exceptions and to the submissions attached to it; from a submission to its disclosure statements; and from an audit sample to its findings.

### 2.7. Counting, Precision and Rounding

All record counters, field counts, and exception counters in this system are exact integers. Percentages and rates — `defect_rate_pct`, `control_denial_rate_pct`, `protected_denial_rate_pct`, `disparity_index`, and the tract statistics `minority_population_pct` and `tract_to_msa_income_pct` — are decimal numbers. Wherever this document says a value is rounded, the rounding is to two decimal places using round-half-up.

Where a calculation rounds more than once, the order in which the roundings happen is part of the specification and is stated at the point of use. In particular, the fair lending disparity index in §3.9 is computed from two already-rounded denial rates, not from the raw ratios; computing it the other way produces a different number and is not what this system does.

Monetary amounts are held in cents as integers (`loan_amount_cents`, `asset_size_usd_cents`, `median_family_income_cents`) and are never rounded. Income is held in whole thousands of dollars as an integer (`income_thousands`).

### 2.8. Optimistic Concurrency on Register Parents

Two write operations in this system supersede an existing row of the caller's own institution, and both are legitimate from an unchanged starting state — which is precisely why neither can be guarded by a state precondition. They are instead guarded by optimistic concurrency control against the parent's `version`.

Opening a filing submission requires the client to supply `expected_institution_version`, carrying the `version` of the `Institution` the client last observed. If that value does not equal the institution's current `version`, the create is rejected with `ERR_STALE_INSTITUTION_VERSION` and HTTP 412, and no `FilingSubmission` row is written at all. The rule exists because a new draft submission supersedes an existing draft submission of the same institution; a client whose view of the register is stale would be discarding a draft it has never seen.

Creating a geocode assignment requires the client to supply `expected_application_version`, carrying the `version` of the target `Application` the client last observed. If that value does not equal the application's current `version`, the create is rejected with `ERR_STALE_APPLICATION_VERSION` and HTTP 412, and the previous assignment's `is_current` flag is left untouched. A stale value means the client has not seen the assignment or the stage change that already moved the row.

Both `expected_institution_version` and `expected_application_version` are required inputs on their respective endpoints — they are not optional, and a request that omits them is malformed. No other endpoint in this system accepts a version field of any kind.

### 2.9. Order of Evaluation for Rejected Requests

When more than one rule would reject a request, the outcome is decided by the first rule to fail in the following strictly ascending order, and no later rule is evaluated. This ordering is observable and is part of the contract.

1. Header authentication — `ERR_UNAUTHENTICATED`, 401.
2. Endpoint role authorisation — `ERR_FORBIDDEN_ROLE`, 403.
3. Institution scope for an acting `InstitutionAdmin` — `ERR_INSTITUTION_SCOPE_VIOLATION`, 403.
4. Path identifier resolution, left to right — the relevant not-found error, 404.
5. Body shape: every required input named in §4 is present, every enum value is a member of its declared set, integers and numbers are of the declared type and within any stated range, arrays are arrays, ISO 8601 datetimes parse, and `limit` and `offset` lie inside the pagination bounds — `ERR_INVALID_REQUEST`, 400.
6. Body foreign-key resolution — the relevant not-found error, 404. This applies to opening a register record, recording a demographic entry, creating a geocode assignment, pinning a tract by manual override, starting an edit run, opening a submission, attaching an edit run to a submission, drawing an audit sample, recording an audit finding, and computing a fair lending analysis.
7. Optimistic concurrency on the supplied parent version — `ERR_STALE_INSTITUTION_VERSION` or `ERR_STALE_APPLICATION_VERSION`, 412, on the two endpoints named in §2.8.
8. State preconditions: the target row is in a state from which the requested transition is declared — `ERR_INVALID_STAGE_TRANSITION`, `ERR_INVALID_SUBMISSION_STATE`, `ERR_EXCEPTION_NOT_OPEN`, `ERR_GEOCODE_NOT_OVERRIDABLE`, `ERR_SAMPLE_NOT_OPEN`, `ERR_APPLICATION_ARCHIVED`, or `ERR_EDIT_RUN_INVALIDATED`, all 409. This step covers every action endpoint and the demographic amendment endpoint.
9. Cross-entity state guards on advancing a register record — `ERR_GEOCODE_UNRESOLVED` or `ERR_MISSING_APPLICANT_DEMOGRAPHICS`, 409.
10. Segregation of duties at certification — `ERR_SEGREGATION_OF_DUTIES`, 403.
11. The four demographic collection rules, in the order given in §3.3 — `ERR_VISUAL_OBSERVATION_NOT_PERMITTED`, then `ERR_DISAGGREGATED_CODE_NOT_PERMITTED`, then `ERR_OBSERVATION_REQUIRED_FOR_IN_PERSON`, then `ERR_NON_NATURAL_PERSON_MISMATCH`, all 422.
12. Cross-field referential accuracy, in this order — `ERR_DENIAL_REASON_REQUIRED`, `ERR_DENIAL_REASON_NOT_PERMITTED`, `ERR_PURCHASER_TYPE_REQUIRED`, `ERR_GEOCODE_TRACT_MISMATCH`, `ERR_EDIT_RUN_INSTITUTION_MISMATCH`, `ERR_FINDING_APPLICATION_NOT_IN_SAMPLE`, all 422.
13. Action-date accuracy, in this order — `ERR_ACTION_DATE_BEFORE_APPLICATION`, `ERR_ACTION_DATE_IN_FUTURE`, `ERR_ACTION_DATE_OUTSIDE_ACTIVITY_YEAR`, all 422.
14. Interval well-formedness — `ERR_INVALID_WINDOW`, 422.
15. Structural constraints, in this order — `ERR_EDIT_RUN_WINDOW_OVERLAP` (409), `ERR_REMEDIATION_WINDOW_OVERLAP` (409), `ERR_DUPLICATE_ULI` (409), `ERR_DUPLICATE_LEI` (409), `ERR_DUPLICATE_DEMOGRAPHIC_ROLE` (409), `ERR_TOO_MANY_RACE_CODES` (422), `ERR_SEVERITY_NOT_VERIFIABLE` (422).
16. Aggregate and quota gates, in this order — `ERR_OPEN_VALIDITY_EDITS` (422), `ERR_VERIFICATION_QUOTA_NOT_MET` (422), `ERR_EMPTY_SAMPLE_POPULATION` (422), `ERR_EMPTY_CONTROL_GROUP` (422).

A practical consequence worth stating explicitly: because segregation of duties is evaluated before the open-edit and quota gates, a certification attempt by the same operator who verified an exception on the attached run surfaces as `ERR_SEGREGATION_OF_DUTIES` even when the run still carries open validity edits and even when the verification quota has not been met. Likewise, because the demographic rules run in the stated order, a visual-observation record on a non–face-to-face application surfaces as `ERR_VISUAL_OBSERVATION_NOT_PERMITTED` and not as the disaggregated-code error, even when both conditions hold.

### 2.10. Cascade Integrity Across the Register

The register, the edit battery, and the annual filing form a chain of derived state, and this platform maintains that chain eagerly: every write that invalidates something downstream propagates immediately, within the same request, rather than being reconciled later. Two cascades in particular reach several entities deep and are specified in full where they occur — the decertification cascade triggered by reopening a locked record (§3.2) and the archival cascade triggered by filing (§3.7).

The invariant behind both is simple to state: an edit run describes a snapshot of the register, and a certification attests to an edit run. If any record in the snapshot stops being clean, the run no longer describes the register and must be invalidated; if a run is invalidated, every submission resting on it loses its attachment and its certification. Institution-level counters are recomputed as part of the same request whenever the records they count change.

Whenever a cascade mutates a row, that row's `updated_at` is refreshed and its `version` is incremented by 1, exactly as for a directly requested mutation.

### 2.11. Segregation of Duties in the Filing Chain

Certification is an attestation, and an attestation is worthless if the attester is also the person who signed off the findings being attested to. The platform enforces this as a hard rule: when a `ComplianceOfficer` certifies a submission, the caller's `X-User-ID` must differ from every `verified_by_user_id` recorded on a `VERIFIED` exception of the attached edit run. If it matches even one, certification is refused with `ERR_SEGREGATION_OF_DUTIES` and HTTP 403.

The rule compares operator identifiers, not roles. Nothing prevents the same human from holding both roles in an organisation; what the platform refuses is one identifier appearing on both sides of the same run.

## 3. Business Logic & Workflows

### 3.1. Onboarding a Reporting Institution and Resolving Its Filing Profile

A reporting bank enters the platform when a `SystemAdmin` registers it for exactly one HMDA activity year. Registration supplies the bank's `lei` — its twenty-character uppercase alphanumeric Legal Entity Identifier — together with its legal `name`, the `activity_year` the register covers (a year between 2020 and 2035 inclusive), and `asset_size_usd_cents`, the bank's total assets at the prior year end expressed in cents. Two optional volume figures may accompany the registration: `prior_year_closed_end_originations` and `prior_year_open_end_originations`, each defaulting to 0 when omitted. An `lei` must be unique across every institution the platform holds; a second registration reusing one is rejected with `ERR_DUPLICATE_LEI`.

From those inputs the platform derives the institution's **filing profile**, and it derives it in a pinned order. The four outputs look mutually dependent — exemption depends on volume, quarterly status depends on volume, and the field requirement depends on both — but there is no iteration to a fixed point. First, the bank is judged *volume-exempt* when its prior-year closed-end originations number fewer than 500 **and** its prior-year open-end originations number fewer than 500; the comparison is strict, so a prior-year count of exactly 500 on either measure removes volume exemption. Second, the bank is judged *asset-exempt* when `asset_size_usd_cents` is at most 1000000000000 cents, that is, ten billion dollars or less. Third, `quarterly_filer` is set true when the sum of the two prior-year origination counts is at least 60000. Fourth, `partial_exemption_eligible` is true only when the bank is volume-exempt and asset-exempt and is not a quarterly filer. Fifth, `required_field_count` is set to 26 for a partially exempt institution and to 48 otherwise. Sixth, `filing_deadline_at` is set to the first of March of the year following `activity_year`, at 23:59:59.000 UTC.

An institution begins life with `filing_posture` of `OPEN` and with every record counter at zero: `total_application_count`, `pending_record_count`, `reportable_record_count`, `excluded_record_count`, `cleared_record_count`, and `open_register_count`. Those counters are maintained continuously thereafter — `total_application_count` counts every register record belonging to the institution, `pending_record_count` counts those whose register-quality dimension reads `PENDING_FIELDS`, `reportable_record_count` counts those reading `COMPLETE`, `EXCEPTION_FLAGGED`, or `CLEARED`, `excluded_record_count` counts those reading `EXCLUDED`, `cleared_record_count` counts those reading `CLEARED`, and `open_register_count` counts every record whose capture stage is anything other than `ARCHIVED`. The `filing_posture` value moves through `OPEN`, `LOCKED_FOR_FILING`, `FILED_YEAR`, and `CLOSED_YEAR` as the annual filing progresses, and it gates the act of filing itself (§3.7).

A bank-side `InstitutionAdmin` may amend the profile, supplying any of `name`, `asset_size_usd_cents`, `prior_year_closed_end_originations`, or `prior_year_open_end_originations`. The amendment re-derives the entire filing profile over the merged row using the same six pinned steps. Because `partial_exemption_eligible` may have flipped, and because that flag decides how many fields a register record must carry, the amendment also re-evaluates the completeness of every register record the institution owns, potentially moving records between `PENDING_FIELDS` and `COMPLETE` in either direction. The institution's `version` increments by 1.

### 3.2. The Register Record: Opening, Capturing, Advancing, Reopening

A register record is opened by a `LoanOfficer`, who names the owning bank with an `institution_id` and supplies the record's `uli` (its Universal Loan Identifier), the `application_date` on which the application was received, the `application_channel` through which it arrived — one of `FACE_TO_FACE`, `MAIL`, `INTERNET`, or `TELEPHONE` — and the four classification fields `loan_type` (`CONVENTIONAL`, `FHA`, `VA`, or `RHS_FSA`), `loan_purpose` (`HOME_PURCHASE`, `HOME_IMPROVEMENT`, `REFINANCING`, `CASH_OUT_REFINANCING`, or `OTHER_PURPOSE`), `occupancy_type` (`PRINCIPAL`, `SECOND`, or `INVESTMENT`), and `lien_status` (`FIRST_LIEN` or `SUBORDINATE_LIEN`), plus `loan_amount_cents`, which must be at least 1. Optionally the officer may already know `income_thousands`, may mark `business_or_commercial_purpose` or `open_end_line_of_credit` (both default false), and may declare `supersedes_application_id` when this row is a corrected replacement for an earlier register record. A `uli` must be unique among the non-superseded records of the same institution; a collision is rejected with `ERR_DUPLICATE_ULI`.

Opening a record sets `stage` to `INTAKE` and runs the completeness calculation described below to set the register-quality dimension. When `supersedes_application_id` is supplied, the earlier record's `is_superseded` flag is set true and that record's `version` increments by 1 — a superseded original stays in the database and stays visible through the corrections listing, but it drops out of the final filing count and out of every analytical population. The owning institution's `total_application_count`, `pending_record_count`, `reportable_record_count`, `excluded_record_count`, and `open_register_count` are all recomputed, and its `version` increments by 1.

**Two independent dimensions.** Every register record carries `stage`, describing how far the field-capture workflow has progressed, and `lar_status`, describing how clean the record currently is. They evolve independently on the same row: a record may perfectly well be `DECISIONED` and `PENDING_FIELDS` at the same time, or `DECISIONED` and `EXCEPTION_FLAGGED`. The capture stages are `INTAKE`, `UNDERWRITING`, `DECISIONED`, `REGISTER_LOCKED`, and `ARCHIVED`, with `ARCHIVED` terminal. The register-quality values are `PENDING_FIELDS` (the initial value), `COMPLETE`, `EXCEPTION_FLAGGED`, `CLEARED`, and `EXCLUDED`; none of them is terminal.

**Completeness.** Whenever a record is opened, amended, has its action recorded, or is reopened, the platform recomputes which fields are applicable to it and how many of them are present. Ten fields are always applicable: `uli`, `application_date`, `application_channel`, `loan_type`, `loan_purpose`, `occupancy_type`, `lien_status`, `loan_amount_cents`, `action_taken`, and `action_taken_date`. If the owning institution is **not** partially exempt, `income_thousands` joins the applicable set, and three further conditional additions apply on top of it: when `action_taken` reads `ORIGINATED`, both `rate_spread` and `purchaser_type` become applicable; when `action_taken` reads `PURCHASED_LOAN`, `purchaser_type` becomes applicable; and when `action_taken` reads `DENIED`, `denial_reason_codes` becomes applicable. A partially exempt institution's records are held to the ten core fields alone, whatever the action. `applicable_field_count` is the size of that set and `captured_field_count` is the number of its members whose value is currently present — non-null, and for array-typed fields non-empty. The enum member `NOT_APPLICABLE`, wherever it may legally be recorded, counts as a present value rather than an absent one.

The register-quality value is then written in a pinned order of three tests. If `business_or_commercial_purpose` is true and `loan_purpose` is none of `HOME_PURCHASE`, `HOME_IMPROVEMENT`, `REFINANCING`, or `CASH_OUT_REFINANCING`, the record becomes `EXCLUDED` with `exclusion_reason` set to `BUSINESS_PURPOSE`; the institution's `excluded_record_count` rises by one and its `pending_record_count` falls by one. Otherwise, if `captured_field_count` equals `applicable_field_count`, the record becomes `COMPLETE` with `exclusion_reason` set back to `NOT_EXCLUDED`, and the institution's `pending_record_count` falls by one while `reportable_record_count` rises by one. Otherwise the record is `PENDING_FIELDS` with `exclusion_reason` of `NOT_EXCLUDED`; a record moving `COMPLETE → PENDING_FIELDS` because an amendment cleared a required field reverses the counter movement, lowering `reportable_record_count` and raising `pending_record_count`. This calculation never writes `EXCEPTION_FLAGGED` and never writes `CLEARED` — those two values belong to the edit battery and its verification cascade — and, crucially, when the record currently reads `EXCEPTION_FLAGGED` or `CLEARED` and this calculation would otherwise yield `COMPLETE`, the register-quality value is left exactly as it was.

**Amending fields.** A `LoanOfficer` may capture or amend `income_thousands`, `loan_amount_cents`, `rate_spread`, `purchaser_type`, `denial_reason_codes`, `occupancy_type`, `lien_status`, `loan_purpose`, and `business_or_commercial_purpose` on a record at its current stage. Every amendment re-runs the completeness calculation, recomputes the institution's record counters, and increments both the record's `version` and the institution's `version` by 1. The most consequential amendment is the one that turns a business-purpose row's `loan_purpose` to `OTHER_PURPOSE`, which drops the record out of the register entirely as `EXCLUDED`.

**Advancing the stage.** Advancing supplies a `to_stage` value and moves the record one step along the capture workflow. `INTAKE → UNDERWRITING` requires that at least one applicant demographic row already exists on the record with an `applicant_role` of `APPLICANT`; without one the advance is refused with `ERR_MISSING_APPLICANT_DEMOGRAPHICS`. `UNDERWRITING → DECISIONED` requires that the record's `application_date` is no later than the current logical clock; a record dated in the future cannot be decisioned, and the refusal carries `ERR_INVALID_STAGE_TRANSITION`. `DECISIONED → REGISTER_LOCKED` carries three preconditions: `action_taken` must already be recorded, otherwise `ERR_INVALID_STAGE_TRANSITION`; the record's current geocode assignment must have resolved to a tract, meaning its status reads either `MATCHED` or `MANUAL_OVERRIDE`, otherwise `ERR_GEOCODE_UNRESOLVED`; and `lar_status` must read either `COMPLETE` or `EXCLUDED`, otherwise `ERR_INVALID_STAGE_TRANSITION`. Any advance request naming a stage not reachable from the record's present stage is likewise `ERR_INVALID_STAGE_TRANSITION`. Every successful advance increments the record's `version` by 1.

**Reopening a locked record — the five-hop decertification cascade.** A `ComplianceAnalyst` who discovers an error in a locked record reopens it, supplying a `reason` for the audit trail. Reopening is only defined for a record whose stage reads `REGISTER_LOCKED`; from any other stage the request is refused with `ERR_INVALID_STAGE_TRANSITION`. The consequences reach five levels deep and all of them happen inside the one request:

1. The record returns `REGISTER_LOCKED → DECISIONED`, and both `action_taken` and `action_taken_date` are cleared. Completeness is recomputed, which necessarily moves the register-quality dimension to `PENDING_FIELDS` — including from `CLEARED`, the one path by which a record leaves `CLEARED` for `PENDING_FIELDS`. The institution's `pending_record_count`, `reportable_record_count`, and `cleared_record_count` are recomputed accordingly, with `cleared_record_count` and `reportable_record_count` each falling by one and `pending_record_count` rising by one when the record had been `CLEARED`.
2. Caused by hop 1: every edit exception naming this record whose status reads `VERIFIED` reverts to `OPEN`, with its `verified_by_user_id`, `verified_at`, and `verification_note` all cleared. The owning edit run's `verified_exception_count` falls, its `open_exception_count` rises, and its `cleared_record_count` falls by one.
3. Caused by hop 2: that edit run's status becomes `INVALIDATED`, because its snapshot no longer describes the register.
4. Caused by hop 3: every filing submission attached to that run whose status reads `EDITS_ATTACHED` or `CERTIFIED` returns to `DRAFT`. On a submission returning from `CERTIFIED`, the attachment and the whole certification are erased — `edit_run_id`, `certified_by_user_id`, `certified_at`, `attestation_text`, and `final_record_count` are all cleared. On a submission returning from `EDITS_ATTACHED`, only `edit_run_id` is cleared.
5. Caused by hop 4: the institution's `filing_posture` returns from `LOCKED_FOR_FILING` to `OPEN`.

The record's `version` and the institution's `version` each increment by 1.

**Archival and its reversal.** A record leaves the working register only by being filed. During filing, every record of the submission's final set whose stage reads `REGISTER_LOCKED` moves `REGISTER_LOCKED → ARCHIVED`, the institution's `open_register_count` is recomputed, and each archived record's `version` increments by 1. If the regulator later rejects that filing, exactly those records move back `ARCHIVED → REGISTER_LOCKED`, the institution's `open_register_count` is recomputed again, `filing_posture` returns to `OPEN`, and each record's `version` increments by 1 once more. While a record is `ARCHIVED`, no mutation may touch it: an attempt to amend its applicant demographics, or to verify an edit exception that names it, is refused with `ERR_APPLICATION_ARCHIVED`.

### 3.3. Applicant Demographics and the Collection-Method Rules

Government monitoring information is the most procedurally constrained data the register carries, because *how* it was obtained changes *what* may be recorded. A `LoanOfficer` records one demographic row per applicant, naming the register record through `application_id` and the applicant through `applicant_role`, which is either `APPLICANT` or `CO_APPLICANT`. At most one row may exist for a given pairing of `application_id` and `applicant_role`; a second attempt is refused with `ERR_DUPLICATE_DEMOGRAPHIC_ROLE`. The row records `collection_method`, `ethnicity_codes`, `race_codes`, and `sex_code`, and may optionally record `is_natural_person` (defaulting to true), `age_years`, and `observation_basis` (defaulting to `NOT_OBSERVED`). A newly recorded row has a status of `RECORDED`.

`collection_method` takes one of four values: `PROVIDED_BY_APPLICANT`, `VISUAL_OBSERVATION_OR_SURNAME`, `NOT_PROVIDED_BY_APPLICANT`, or `NOT_APPLICABLE`. `observation_basis` records the basis when observation was used and takes `NOT_OBSERVED`, `SURNAME`, or `VISUAL`. `sex_code` takes `MALE`, `FEMALE`, `BOTH`, `INFO_NOT_PROVIDED`, or `NOT_APPLICABLE`. `ethnicity_codes` is an array drawn from the aggregate categories `HISPANIC_OR_LATINO`, `NOT_HISPANIC_OR_LATINO`, `INFO_NOT_PROVIDED`, and `NOT_APPLICABLE`, together with the disaggregated subcategories `MEXICAN`, `PUERTO_RICAN`, `CUBAN`, and `OTHER_HISPANIC`. `race_codes` is an array drawn from the aggregate categories `AMERICAN_INDIAN`, `ASIAN`, `BLACK`, `PACIFIC_ISLANDER`, `WHITE`, `INFO_NOT_PROVIDED`, and `NOT_APPLICABLE`, together with the disaggregated subcategories `ASIAN_INDIAN`, `CHINESE`, `FILIPINO`, `JAPANESE`, `KOREAN`, `VIETNAMESE`, `OTHER_ASIAN`, `NATIVE_HAWAIIAN`, `GUAMANIAN`, `SAMOAN`, and `OTHER_PACIFIC_ISLANDER`.

Four collection rules guard every demographic write, whether the row is being recorded for the first time or amended, and they are evaluated in the following order — the first to fail decides the response, and each carries HTTP 422:

1. **Visual observation requires an in-person application.** `VISUAL_OBSERVATION_OR_SURNAME` may be used as the `collection_method` only when the parent register record's `application_channel` reads `FACE_TO_FACE`. On a mail, internet, or telephone application it is refused with `ERR_VISUAL_OBSERVATION_NOT_PERMITTED`.
2. **Observation may only produce aggregate categories.** When `collection_method` is `VISUAL_OBSERVATION_OR_SURNAME`, every supplied ethnicity code and every supplied race code must be one of the aggregate categories listed above; a disaggregated subcategory is forbidden, and so is `INFO_NOT_PROVIDED` in either array. In the same situation `sex_code` must be `MALE`, `FEMALE`, or `BOTH`. Any of these violations is refused with `ERR_DISAGGREGATED_CODE_NOT_PERMITTED`. The reasoning is that an officer looking at an applicant can record a broad category but cannot honestly record a subcategory, and cannot record that the applicant declined to provide what the officer observed for themselves.
3. **In-person applications may not simply decline.** When the parent register record's `application_channel` reads `FACE_TO_FACE` and `is_natural_person` is true, `collection_method` may not be `NOT_PROVIDED_BY_APPLICANT`; the officer is required to record ethnicity, race, and sex by visual observation or surname when the applicant declines to state them. Violation is refused with `ERR_OBSERVATION_REQUIRED_FOR_IN_PERSON`.
4. **Non-natural persons carry nothing.** When `is_natural_person` is false — a trust, an estate, or another non-natural applicant — `collection_method` must be `NOT_APPLICABLE`, and `ethnicity_codes`, `race_codes`, and `sex_code` must all carry nothing but `NOT_APPLICABLE`. Anything else is refused with `ERR_NON_NATURAL_PERSON_MISMATCH`.

Independently of the four rules, an array size limit applies to both recording and amendment: `race_codes` may carry at most 5 entries and `ethnicity_codes` at most 2. Exceeding either limit is refused with `ERR_TOO_MANY_RACE_CODES`.

Amendment merges the supplied values — any of `collection_method`, `ethnicity_codes`, `race_codes`, `sex_code`, `age_years`, `observation_basis`, and `is_natural_person` — into the existing row, then re-evaluates all four collection rules and the array limits against the *merged* result rather than against the submitted fragment. A successful amendment moves the row `RECORDED → AMENDED` and increments its `version` by 1. Amendment is refused with `ERR_APPLICATION_ARCHIVED` when the parent register record's stage reads `ARCHIVED`.

The demographic row also has a gating role in the capture workflow: no record may leave `INTAKE` until an `APPLICANT` row exists on it, as §3.2 describes.

### 3.4. Geocoding the Secured Property and Assigning a Census Tract

Census tract reference data is loaded by a `SystemAdmin`, one row at a time. Each `CensusTract` carries an eleven-digit `tract_code`, the five-digit `county_fips` and two-letter `state_code` locating it, its five-digit `msa_md_code`, and four statistics used downstream: `minority_population_pct` (the tract's minority population share as a percentage), `tract_to_msa_income_pct` (tract median family income as a percentage of the MSA median), `owner_occupied_units` (which drives disclosure suppression in §3.7), and `median_family_income_cents`. Tract rows are never modified once loaded.

A `LoanOfficer` geocodes the secured property by creating a geocode assignment against a register record. The request names the record with `application_id`, carries `expected_application_version` as §2.8 requires, and supplies the property's `street_address`, `city`, `state_code`, `zip_code`, and `county_fips`. It may optionally supply `submitted_tract_code`, an eleven-digit tract code the loan officer asserts is correct.

Matching runs immediately and deterministically. When `submitted_tract_code` is supplied, the candidate set is every loaded tract whose `tract_code` equals it **and** whose `county_fips` equals the request's `county_fips` **and** whose `state_code` equals the request's `state_code`. When no `submitted_tract_code` is supplied, the candidate set is every loaded tract whose `county_fips` and `state_code` both equal the request's. All comparisons are exact, case-sensitive string equality, and no status filter narrows the tract table because tract data is immutable reference data. The number of candidates is stored as `candidate_count`, and it decides the outcome:

- Exactly one candidate: the assignment moves `PENDING → MATCHED`, `census_tract_id` is set to that tract, and `msa_md_code` is copied from it.
- No candidates: the assignment moves `PENDING → NOT_MATCHED`, with `census_tract_id` and `msa_md_code` both left null.
- Two or more candidates, which can only arise when no `submitted_tract_code` was supplied: the assignment moves `PENDING → AMBIGUOUS`, with `census_tract_id` and `msa_md_code` both left null.

Creating a new assignment always sets the record's previous assignment's `is_current` flag to false, so exactly one assignment per record is current at any moment, and it increments the register record's `version` by 1. The full history remains readable through the record's geocode listing, newest last.

An `AMBIGUOUS` or `NOT_MATCHED` assignment is dead weight on the register — it blocks the record from locking — so a `ComplianceAnalyst` resolves it by manual override, naming the `census_tract_id` to pin and recording an `override_reason` justifying the choice. Override is defined only from `AMBIGUOUS → MANUAL_OVERRIDE` and from `NOT_MATCHED → MANUAL_OVERRIDE`; attempting it on an assignment that is `PENDING`, already `MATCHED`, or already overridden is refused with `ERR_GEOCODE_NOT_OVERRIDABLE`. The pinned tract must sit in the same jurisdiction as the property: its `county_fips` and its `state_code` must both equal the assignment's own, and a mismatch on either is refused with `ERR_GEOCODE_TRACT_MISMATCH`. A successful override stores the tract, copies `msa_md_code` from it, stores `override_reason`, and increments the assignment's `version` by 1. Both `MATCHED` and `MANUAL_OVERRIDE` are terminal for the assignment.

### 3.5. Recording the Action Taken and Its Date

The single most scrutinised pair of fields on a register record is the action the institution took and the date it took it. A `LoanOfficer` records them together, supplying `action_taken` and `action_taken_date`, and may in the same request supply the fields that only become applicable once the action is known: `denial_reason_codes`, `purchaser_type`, `rate_spread`, and `income_thousands`.

`action_taken` is one of `ORIGINATED`, `APPROVED_NOT_ACCEPTED`, `DENIED`, `WITHDRAWN`, `FILE_CLOSED_INCOMPLETE`, `PURCHASED_LOAN`, `PREAPPROVAL_DENIED`, or `PREAPPROVAL_APPROVED_NOT_ACCEPTED`. `denial_reason_codes` is an array whose members are drawn from `DEBT_TO_INCOME`, `EMPLOYMENT_HISTORY`, `CREDIT_HISTORY`, `COLLATERAL`, `INSUFFICIENT_CASH`, `UNVERIFIABLE_INFO`, `INCOMPLETE_APPLICATION`, `MORTGAGE_INSURANCE_DENIED`, and `OTHER`, and it defaults to an empty array on a newly opened record. `purchaser_type` is one of `NOT_APPLICABLE`, `FANNIE_MAE`, `FREDDIE_MAC`, `GINNIE_MAE`, `PRIVATE_SECURITIZER`, or `OTHER`.

Three referential rules bind the action to its companion fields, evaluated in this order. A denial — `action_taken` of `DENIED` or `PREAPPROVAL_DENIED` — requires a non-empty `denial_reason_codes` array, and its absence is refused with `ERR_DENIAL_REASON_REQUIRED`. Conversely, any action that is neither `DENIED` nor `PREAPPROVAL_DENIED` forbids a non-empty `denial_reason_codes` array, and supplying one is refused with `ERR_DENIAL_REASON_NOT_PERMITTED`. And an action of `PURCHASED_LOAN` requires `purchaser_type` to be present and to be something other than `NOT_APPLICABLE`, since a purchased loan by definition has a purchaser; a missing or `NOT_APPLICABLE` value is refused with `ERR_PURCHASER_TYPE_REQUIRED`.

Three date-accuracy rules then apply, again in a fixed order. The `action_taken_date` may not precede the record's `application_date` — an institution cannot act on an application before receiving it — and a violation is refused with `ERR_ACTION_DATE_BEFORE_APPLICATION`. It may not be later than the current logical clock, since an institution cannot act in the future; a violation is refused with `ERR_ACTION_DATE_IN_FUTURE`. And its calendar year must equal the owning institution's `activity_year`, because a register covers exactly one year; a violation is refused with `ERR_ACTION_DATE_OUTSIDE_ACTIVITY_YEAR`.

Once all six rules pass, `action_taken` and `action_taken_date` are stored, the completeness calculation of §3.2 re-runs — commonly moving the record `PENDING_FIELDS → COMPLETE`, because the action and its date are two of the ten always-applicable fields and because the action may add the conditional ones — the institution's record counters are recomputed, and both the record's `version` and the institution's `version` increment by 1.

### 3.6. The Edit Battery: Running, Verifying, Clearing

**Opening a run.** A `ComplianceAnalyst` runs the edit battery over an institution's register, naming the bank with `institution_id`, declaring the `scope` of the run as either `FULL` or `INCREMENTAL`, and reserving a review window on the institution with `window_start` and `window_end`. Each run is stamped with `run_index`, a one-based counter that increments in creation order within the institution. A run's window must be well formed: `window_end` must be strictly later than `window_start`, and a run whose end is at or before its start is refused with `ERR_INVALID_WINDOW`.

Review windows on one institution are **half-open**, covering their start instant and everything up to but excluding their end instant. A new run is refused with `ERR_EDIT_RUN_WINDOW_OVERLAP` when an existing run of the same institution whose status is anything other than `INVALIDATED` satisfies both of the following: the new run's start is strictly earlier than the existing run's end, and the existing run's start is strictly earlier than the new run's end. Touching windows are therefore accepted — a new run starting at exactly the instant an existing run ends does not collide — while a run already invalidated never blocks anything.

**The snapshot.** The run freezes a snapshot of the register at the moment it starts: every register record of the institution that has an `action_taken` recorded, whose `is_superseded` flag is false, whose `lar_status` is anything other than `EXCLUDED`, and whose `stage` reads either `DECISIONED` or `REGISTER_LOCKED`. The snapshot is ordered by `created_at` ascending — never by identifier — and its size is stored as `snapshot_record_count`. Records outside the snapshot are untouched by the run in every respect.

**The edits.** Each snapshot record is walked in snapshot order, and within a record the eight record-level edits are evaluated in the fixed catalogue order `S300`, `S301`, `V610`, `V620`, `V631`, `Q607`, `Q615`, `Q620`. Every edit that fires appends one exception in that same order, so the creation ordering of exceptions is fully deterministic. Each exception records its `edit_code`, its `severity`, the `field_name` the edit points at, a human-readable `message`, the `edit_run_id` of the run that raised it, and the `application_id` of the record it concerns.

- `S300`, severity `SYNTACTICAL`, on `uli`: fires when the record's `uli` is shorter than 23 characters.
- `S301`, severity `SYNTACTICAL`, on `uli`: fires when the `uli` contains any character that is neither an uppercase letter A through Z nor a digit 0 through 9.
- `V610`, severity `VALIDITY`, on `income_thousands`: fires when `income_thousands` is absent, the owning institution is not partially exempt, and `action_taken` is one of `ORIGINATED`, `APPROVED_NOT_ACCEPTED`, or `DENIED`.
- `V620`, severity `VALIDITY`, on `rate_spread`: fires when `rate_spread` is present while `action_taken` is either `WITHDRAWN` or `FILE_CLOSED_INCOMPLETE` — there is no rate spread on a loan that was never made.
- `V631`, severity `VALIDITY`, on `census_tract_id`: fires when the record has no current geocode assignment at all, or when its current assignment's status is `AMBIGUOUS`, `NOT_MATCHED`, or `PENDING`.
- `Q607`, severity `QUALITY`, on `loan_amount_cents`: fires when `income_thousands` is present and the loan amount in cents exceeds five times the applicant's gross annual income. Because income is held in whole thousands of dollars, the comparison converts it by multiplying `income_thousands` by 100000 to reach cents and then by the loan-to-income multiple of 5; the comparison is strict, so a loan at exactly five times income does not fire the edit.
- `Q615`, severity `QUALITY`, on `action_taken_date`: fires when the whole number of days between `application_date` and `action_taken_date` exceeds 180, the half-year mark from receipt to decision. Day differences throughout this system are computed as the elapsed seconds divided by 86400 and rounded down to a whole number, and the comparison is strict.
- `Q620`, severity `QUALITY`, on `loan_amount_cents`: fires when `loan_amount_cents` is below 100000 cents, that is, below one thousand dollars — an amount too small to be a plausible mortgage.

After the per-record walk, one macro edit is evaluated once over the whole snapshot. `Q800`, severity `MACRO`, on `action_taken`, fires when the snapshot holds at least one record and the share of snapshot records whose `action_taken` reads `WITHDRAWN`, expressed as a percentage of `snapshot_record_count`, is strictly greater than 30.0 percent. Percentage comparisons here use exact arithmetic rather than a floating approximation. A macro exception carries a null `application_id`, since it describes the register as a whole rather than any one record.

**The run's counters.** `syntactical_count`, `validity_count`, `quality_count`, and `macro_count` hold the number of exceptions raised at each severity, and `total_exception_count` is their sum. Every newly raised exception starts `OPEN`, so `open_exception_count` initially equals `total_exception_count`, while `verified_exception_count` and `stale_exception_count` both start at zero. `cleared_record_count` holds the number of snapshot records that drew no record-level exception at all.

**Effect on register quality.** Each snapshot record that drew at least one record-level exception moves to `EXCEPTION_FLAGGED` — from `COMPLETE`, from `PENDING_FIELDS`, or back from `CLEARED` if a later run finds a new problem on a record an earlier run had cleared, in which case the institution's `cleared_record_count` falls by one. Each snapshot record that drew none moves from `COMPLETE` to `CLEARED`, raising both the run's `cleared_record_count` and the institution's `cleared_record_count` by one. The macro edit never flags an individual record.

**Superseding earlier runs.** Completing a run supersedes the institution's earlier work: every exception belonging to every earlier non-invalidated run of the same institution moves to `STALE` — from `OPEN`, decrementing that run's `open_exception_count` and incrementing its `stale_exception_count`, or from `VERIFIED`, decrementing that run's `verified_exception_count` and incrementing its `stale_exception_count` — and each of those earlier runs moves to `INVALIDATED`. As always when a run is invalidated, every filing submission attached to it whose status reads `EDITS_ATTACHED` or `CERTIFIED` returns to `DRAFT`. `STALE` is terminal for an exception.

**Where the run lands.** A run begins in `RUNNING` and never remains there past the end of the request that created it. If at least one exception was raised, it settles `RUNNING → COMPLETED`. If none was raised, it settles `RUNNING → CLEARED_ALL`, its `cleared_record_count` is set equal to `snapshot_record_count`, and its `required_verified_quota` is zero. The institution's `version` increments by 1.

**The verification quota.** For a completed run, `required_verified_quota` fixes how much analyst review must happen before an officer may certify. It is computed exactly once, inside the run that creates it, and is never recomputed while exceptions are being worked — this is deliberate, because verifying an exception clears records, which would change what counts as reportable, which would change the quota, and the platform breaks that circularity by pinning the base to the snapshot frozen at run start, before any verification has happened. The raw quota is one tenth of `snapshot_record_count`, rounded up to the next whole number; `required_verified_quota` is then the smaller of that raw quota and the sum of `quality_count` and `macro_count`, so a run can never demand more verifications than it has verifiable exceptions.

**Verifying an exception.** A `ComplianceAnalyst` verifies an exception by supplying a `verification_note` explaining why the flagged value is nonetheless correct. Verification is defined only from `OPEN`; an exception already `VERIFIED` or `STALE` is refused with `ERR_EXCEPTION_NOT_OPEN`. Only `QUALITY` and `MACRO` exceptions may be verified at all — `SYNTACTICAL` and `VALIDITY` exceptions describe data that is simply wrong and must be corrected in the register and cleared by a later run, so verifying one is refused with `ERR_SEVERITY_NOT_VERIFIABLE`. When the exception names a register record, that record's stage may not read `ARCHIVED`, and an attempt against an archived record is refused with `ERR_APPLICATION_ARCHIVED`.

A successful verification moves the exception `OPEN → VERIFIED`, stores the `verification_note`, records the acting analyst's identifier as `verified_by_user_id` and the current logical clock as `verified_at`, decrements the run's `open_exception_count` by one, increments its `verified_exception_count` by one, and increments the exception's `version` by 1. It then bubbles upward in three hops: if the record now carries no open exception from the current run, it moves `EXCEPTION_FLAGGED → CLEARED` and the institution's `cleared_record_count` rises by one; caused by that, the run's own `cleared_record_count` rises by one; and caused by that, when the run's `cleared_record_count` reaches `snapshot_record_count`, the run moves `COMPLETED → CLEARED_ALL`.

The reverse path exists too. When a register record is reopened (§3.2), its `VERIFIED` exceptions revert `VERIFIED → OPEN` with `verified_by_user_id`, `verified_at`, and `verification_note` all cleared, and the owning run moves to `INVALIDATED` from either `COMPLETED` or `CLEARED_ALL`. `INVALIDATED` is terminal for a run.

### 3.7. The Annual Filing Cycle and Public Disclosure

**Opening a submission.** A `ComplianceOfficer` opens a filing submission by naming the institution with `institution_id` and supplying `expected_institution_version` as §2.8 requires. The new submission starts in `DRAFT` and is stamped with `submission_index`, a one-based counter incrementing in creation order within the institution. Its `activity_year` and its `deadline_at` are copied from the institution at creation — `deadline_at` from `filing_deadline_at`, so a submission carries the deadline in force when it was opened even if the institution is later amended. Any existing `DRAFT` submission of the same institution has its `is_superseded` flag set true, and the institution's `version` increments by 1.

**Two record counts, one base set.** A submission carries two counts of the register, and they are computed from the identical base set: every register record of the institution that has an `action_taken` recorded and whose `action_taken_date` falls in the institution's `activity_year`. `provisional_record_count` is frozen at creation and counts the base-set records whose `lar_status` is anything other than `EXCLUDED` — so it includes records still `PENDING_FIELDS` or `EXCEPTION_FLAGGED`, and it includes superseded originals. `final_record_count` is frozen at certification and counts only the base-set records whose `lar_status` reads `CLEARED` and whose `is_superseded` flag is false. Against the same database state the final count is never greater than the provisional one, and the two differ whenever any record is superseded, pending, or exception-flagged. Before certification, `final_record_count` is null.

**Attaching a run.** The officer binds a completed edit run to the draft with an `edit_run_id`. Attachment is defined only from `DRAFT`; from any other status it is refused with `ERR_INVALID_SUBMISSION_STATE`. The named run must belong to the same institution as the submission, and a run from another bank is refused with `ERR_EDIT_RUN_INSTITUTION_MISMATCH`. The run's status must read either `COMPLETED` or `CLEARED_ALL`; a run still `RUNNING`, or one already `INVALIDATED`, is refused with `ERR_EDIT_RUN_INVALIDATED`. Attachment moves the submission `DRAFT → EDITS_ATTACHED`, stores `edit_run_id`, and increments the submission's `version` by 1.

**Certification.** The officer attests to the register by supplying `attestation_text`. Certification is defined only from `EDITS_ATTACHED`; from any other status it is refused with `ERR_INVALID_SUBMISSION_STATE`. Three further gates then apply in order. First, segregation of duties as described in §2.11: the officer's identifier must not match any `verified_by_user_id` on a `VERIFIED` exception of the attached run, and a match is refused with `ERR_SEGREGATION_OF_DUTIES`. Second, the attached run must carry no `OPEN` exception whose `severity` is `SYNTACTICAL` or `VALIDITY` — those describe data that is wrong rather than merely unusual, and they can only be cleared by fixing the register and running the battery again; an attempt while any remains is refused with `ERR_OPEN_VALIDITY_EDITS`. Third, the run's `verified_exception_count` must have reached at least its `required_verified_quota`, and a shortfall is refused with `ERR_VERIFICATION_QUOTA_NOT_MET`.

A successful certification moves the submission `EDITS_ATTACHED → CERTIFIED`, records `certified_by_user_id` as the acting officer's identifier and `certified_at` as the current logical clock, stores `attestation_text`, freezes `final_record_count` as described above, sets the institution's `filing_posture` to `LOCKED_FOR_FILING`, and increments the institution's `version` by 1. From this moment the institution is locked for filing, and reopening any record in it unwinds the certification through the cascade of §3.2.

**Filing and the deadline.** Filing takes no input beyond the submission itself. It is defined only from `CERTIFIED`, and it additionally requires that the institution's `filing_posture` reads `LOCKED_FOR_FILING`; either failure is refused with `ERR_INVALID_SUBMISSION_STATE`. Filing then executes three cascading hops plus a publication step:

1. The submission moves `CERTIFIED → FILED` and `filed_at` is set to the current logical clock. Lateness is evaluated against `deadline_at`: `is_late` is true only when `filed_at` is strictly later than `deadline_at`, so a filing landing exactly on the deadline instant is on time. When the filing is on time `late_by_days` is 0; when it is late, `late_by_days` is the elapsed seconds between `deadline_at` and `filed_at` divided by 86400 and rounded **up** to the next whole day, which means any lateness at all produces at least 1. The institution's `filing_posture` becomes `FILED_YEAR`.
2. Caused by hop 1: every register record of the submission's final set whose stage reads `REGISTER_LOCKED` moves `REGISTER_LOCKED → ARCHIVED`.
3. Caused by hop 2: the institution's `open_register_count` is recomputed, and when it reaches 0 the institution's `filing_posture` moves `FILED_YEAR → CLOSED_YEAR`.

The institution's `version` increments by 1.

**Publication and suppression.** Filing also publishes exactly two disclosure artifacts, appended in this order: first a statement whose `statement_type` reads `MODIFIED_LAR`, then one whose `statement_type` reads `DISCLOSURE_REPORT`. Both carry the same numbers, and both carry `published_at` set to the logical clock at filing and a `submission_id` naming the filing that produced them. `record_count` on each equals the submission's `final_record_count`.

Suppression protects borrower privacy in thinly populated geographies. The final record set is grouped by the census tract of each record's current geocode assignment; records whose current assignment carries no tract at all form one additional group. A group is suppressed when any one of three conditions holds: it is the group of records with no tract; or it holds fewer than 5 records; or the tract's `owner_occupied_units` is below 500. Both numeric comparisons are strict, so a group of exactly 5 records in a tract with exactly 500 owner-occupied units is not suppressed on either ground. `tract_suppression_count` is the number of suppressed groups, `suppressed_record_count` is the total number of records inside them, and `redacted_field_count` is `suppressed_record_count` multiplied by 3, the three fields redacted from each suppressed record. Only the final record set ever appears in a disclosure statement — pending, exception-flagged, excluded, and superseded records never do.

**Examination.** An `Examiner` reviews a filed submission by supplying a `decision` of either `ACCEPT` or `REJECT`, and on a rejection a `rejection_reason` recording the examiner's text. Review is defined only from `FILED`; from any other status it is refused with `ERR_INVALID_SUBMISSION_STATE`. An acceptance moves the submission `FILED → ACCEPTED`, which is terminal — nothing further happens to the register. A rejection moves it `FILED → REJECTED`, stores `rejection_reason`, returns every record archived by this filing from `ARCHIVED` back to `REGISTER_LOCKED`, sets the institution's `filing_posture` back to `OPEN`, and recomputes `open_register_count`. Both the submission's `version` and the institution's `version` increment by 1.

**Resubmission closes the loop.** A `ComplianceOfficer` returns a rejected submission to draft by supplying a `reason`, which is defined only from `REJECTED` and otherwise refused with `ERR_INVALID_SUBMISSION_STATE`. The submission moves `REJECTED → DRAFT`, its `resubmission_count` rises by one, and every downstream field is cleared so the cycle can begin again cleanly: `edit_run_id`, `certified_by_user_id`, `certified_at`, `attestation_text`, `final_record_count`, `filed_at`, `is_late`, and `late_by_days`.

### 3.8. The Data Scrub: Audit Sampling and Defect Rates

Filing correctly is not the same as filing accurately, so a `ComplianceAnalyst` periodically re-keys register fields from source documents and measures how often they disagree. The analyst draws a sample by naming the institution with `institution_id`, choosing a `method` of either `SYSTEMATIC_INTERVAL` or `STRATIFIED_BY_ACTION`, bounding the review with `period_start` and `period_end`, and declaring `fields_reviewed_per_record`, the number of register fields re-keyed per sampled record, which must be at least 1. Each sample is stamped with `sample_index`, a one-based counter incrementing in creation order within the institution. The sampling period is **closed**: `period_end` must be no earlier than `period_start`, and a reversed period is refused with `ERR_INVALID_WINDOW`.

The candidate population is every register record of the institution with an `action_taken` recorded, whose `action_taken_date` falls on or after `period_start` and on or before `period_end`, whose `lar_status` is one of `COMPLETE`, `EXCEPTION_FLAGGED`, or `CLEARED`, and whose `is_superseded` flag is false. Candidates are ordered by `created_at` ascending — never by identifier — and their number is stored as `population_size`. An empty candidate set is refused with `ERR_EMPTY_SAMPLE_POPULATION`.

Sizing is a step function of the population, clamped from three directions. The tier percentage is 10 percent when `population_size` is at most 30, 30 percent when it is at most 100, 15 percent when it is at most 500, and 5 percent above that. The raw draw is `population_size` multiplied by that tier percentage, rounded up to the next whole number. `sample_size` is then the smallest of three quantities: the larger of the raw draw and the minimum sample of 5, the maximum sample of 50, and `population_size` itself — so a tiny population is sampled in full rather than over-drawn, and a vast one is capped at fifty records.

Selection is a systematic walk. The stride is `population_size` divided by `sample_size` and rounded down, with a floor of 1. `selected_application_ids` then holds, in order, the identifiers of the candidates found at positions zero, one stride, two strides, and so on, taking as many entries as `sample_size` demands. When `method` reads `STRATIFIED_BY_ACTION`, the candidate list is first ordered by `action_taken` in the enumeration order given in §3.5 and only then by `created_at` ascending within each action, and the same stride walk is applied to that reordered list. A newly drawn sample starts in `DRAFT`.

**Findings.** The analyst records one finding per re-keyed field, naming the sample with `audit_sample_id` and the record with `application_id`, identifying the `field_name` re-keyed, and supplying both `recorded_value` (what the register says) and `source_document_value` (what the document says) together with a `severity` of `MATERIAL` or `NON_MATERIAL`. The finding also occupies a remediation window on the record, given by `remediation_start` and `remediation_end`; that window is **closed**, `remediation_end` may not precede `remediation_start`, and a reversed window is refused with `ERR_INVALID_WINDOW`. Because the same record cannot be under two simultaneous remediation efforts, a new finding is refused with `ERR_REMEDIATION_WINDOW_OVERLAP` when another finding on the same `application_id` whose `resolution` still reads `OPEN` satisfies both of the following: the new window's start is no later than the existing window's end, and the existing window's start is no later than the new window's end. Because the window is closed at both ends, touching endpoints do collide — a new window beginning at exactly the instant an existing one ends is a conflict.

A finding may only be recorded while the sample is still open: once the sample has closed, whether `CLOSED_CLEAN` or `CLOSED_WITH_FINDINGS`, a new finding against it is refused with `ERR_SAMPLE_NOT_OPEN`. A finding may only name a record the sample actually drew: an `application_id` absent from the sample's `selected_application_ids` is refused with `ERR_FINDING_APPLICATION_NOT_IN_SAMPLE`. On acceptance, `is_defect` is derived as whether `recorded_value` and `source_document_value` differ, compared exactly and case-sensitively; `resolution` starts at `OPEN`. The sample's `defect_count` — its own findings marked as defects — and `records_with_defect_count` — the number of distinct records among those defect findings — are recomputed. The very first finding on a sample moves it `DRAFT → IN_REVIEW`.

**Closing and the two defect-rate variants.** The analyst closes the sample by declaring a `defect_rate_basis` of either `FIELD_WEIGHTED` or `RECORD_WEIGHTED`, and the choice materially changes the published number. Closing is defined only from `DRAFT` or `IN_REVIEW`; a sample already closed is refused with `ERR_SAMPLE_NOT_OPEN`. The total field count reviewed across the sample is `sample_size` multiplied by `fields_reviewed_per_record`. Under `FIELD_WEIGHTED`, `defect_rate_pct` is `defect_count` divided by that total field count, multiplied by 100, and rounded to two decimal places — several defects on one record dilute across every field reviewed in the sample. Under `RECORD_WEIGHTED`, `defect_rate_pct` is `records_with_defect_count` divided by `sample_size`, multiplied by 100, and rounded to two decimal places — several defects on one record collapse to a single defective record. Against identical findings the two variants return different percentages, which is why the basis is recorded on the sample alongside the rate.

Where the sample lands depends on its defects. With `defect_count` at zero the sample closes `CLOSED_CLEAN` with `defect_rate_pct` of 0.00, whether it closes from `DRAFT` or from `IN_REVIEW`. With at least one defect it closes `IN_REVIEW → CLOSED_WITH_FINDINGS` and `defect_rate_pct` is computed under the chosen variant. In both closures from `IN_REVIEW`, every finding belonging to the sample moves its `resolution` from `OPEN` to `ACCEPTED_AS_IS`. Both closed statuses are terminal.

### 3.9. Fair Lending Analysis from Register Data

The register's ultimate purpose is to make lending patterns measurable, and the platform closes the loop by computing denial-rate disparities directly from the data it holds. A `ComplianceAnalyst` requests an analysis by naming the institution with `institution_id`, choosing a `basis` of `RACE`, `ETHNICITY`, or `SEX`, and identifying the two groups to compare through `control_group_code` and `protected_group_code`, each a demographic code matched against the record's `APPLICANT` demographic row. The comparison is bounded by `period_start` and `period_end`, and the period is closed at both ends. Each analysis is stamped with `analysis_index`, a one-based counter incrementing in creation order within the institution.

The analysis universe is every register record of the institution with an `action_taken` recorded, whose `action_taken_date` falls on or after `period_start` and on or before `period_end`, whose `is_superseded` flag is false, and whose `lar_status` is anything other than `EXCLUDED`. A record belongs to a group when its `APPLICANT` demographic row carries the group's code: in `race_codes` when the basis is `RACE`, in `ethnicity_codes` when the basis is `ETHNICITY`, and as the row's `sex_code` when the basis is `SEX`. A record counts as denied when its `action_taken` reads either `DENIED` or `PREAPPROVAL_DENIED`.

`control_total` and `protected_total` hold the two group sizes, and `control_denied` and `protected_denied` hold the denials within each. If either group is empty the analysis is refused with `ERR_EMPTY_CONTROL_GROUP`, since a disparity against nothing is meaningless.

The index is then computed in a pinned three-step order, and the order of rounding is part of the answer. First, `control_denial_rate_pct` is `control_denied` divided by `control_total`, multiplied by 100, and rounded to two decimal places. Second, `protected_denial_rate_pct` is `protected_denied` divided by `protected_total`, multiplied by 100, and rounded to two decimal places. Third, `disparity_index` is computed **from those two already-rounded rates**, not from the raw ratios: if both rates are 0.00, the index is 100.00, because two groups that were never denied are treated as identical; if only the control rate is 0.00, the index is capped at 999.99, because dividing by a zero control rate is undefined and the platform reports the maximum rather than failing; otherwise the index is `protected_denial_rate_pct` divided by `control_denial_rate_pct`, multiplied by 100, and rounded to two decimal places. Dividing the raw ratios and rounding once at the end yields a different number and is explicitly not what this system computes.

`significance_flag` bands the index: `SEVERE` when `disparity_index` is at least 200.0, otherwise `ELEVATED` when it is at least 125.0, otherwise `NOT_SIGNIFICANT`. The analysis then resolves its own status in the same request — an analysis flagged `SEVERE` settles `COMPUTED → ESCALATED`, while one flagged `ELEVATED` or `NOT_SIGNIFICANT` settles `COMPUTED → CLEARED`. Both `ESCALATED` and `CLEARED` are terminal; an analysis is a point-in-time measurement and is never recomputed in place.

## 4. Endpoint Definitions

All endpoints are mounted under `/hmda`, with the single exception of the clock-driving surface. An endpoint that brings a new resource into existence responds with HTTP 201 and returns the created resource in `data`; every other successful call responds with HTTP 200, returning the updated resource for state-changing actions, the requested resource for single reads, and an array for list reads. Note that advancing a register record's capture stage, recording its action taken, and reopening it are all modifications of an existing record and therefore respond with 200, as do all of the submission and audit-sample actions. The list endpoints below accept the pagination parameters of §2.3 together with the filters named in their descriptions; the request bodies and response side effects are not repeated here, because §3 is the normative account of both.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/hmda/institutions` | Register a reporting bank for one HMDA activity year | SystemAdmin |
| PATCH | `/hmda/institutions/{id}` | Amend the institution profile; re-derives the whole filing profile | InstitutionAdmin |
| GET | `/hmda/institutions/{id}` | Read one institution with all derived counters | SystemAdmin, InstitutionAdmin, ComplianceAnalyst, ComplianceOfficer, LoanOfficer, Examiner |
| GET | `/hmda/institutions/{id}/applications` | List the institution's register records; filterable by `stage` and by `lar_status` | SystemAdmin, InstitutionAdmin, ComplianceAnalyst, ComplianceOfficer, LoanOfficer, Examiner |
| GET | `/hmda/institutions/{id}/edit-runs` | List the institution's edit runs; filterable by `status` | SystemAdmin, InstitutionAdmin, ComplianceAnalyst, ComplianceOfficer, Examiner |
| GET | `/hmda/institutions/{id}/submissions` | List the institution's filing submissions; filterable by `status` | SystemAdmin, InstitutionAdmin, ComplianceAnalyst, ComplianceOfficer, Examiner |
| GET | `/hmda/institutions/{id}/audit-samples` | List the institution's audit scrub samples; filterable by `status` | SystemAdmin, InstitutionAdmin, ComplianceAnalyst, ComplianceOfficer, Examiner |
| GET | `/hmda/institutions/{id}/fair-lending-analyses` | List the institution's fair lending analyses; filterable by `basis` and by `status` | SystemAdmin, InstitutionAdmin, ComplianceAnalyst, ComplianceOfficer, Examiner |
| POST | `/hmda/census-tracts` | Load one census tract reference row | SystemAdmin |
| GET | `/hmda/census-tracts/{id}` | Read one census tract | SystemAdmin, InstitutionAdmin, ComplianceAnalyst, ComplianceOfficer, LoanOfficer, Examiner |
| GET | `/hmda/census-tracts/{id}/geocode-assignments` | List assignments resolved to this tract; filterable by `is_current` | SystemAdmin, InstitutionAdmin, ComplianceAnalyst, ComplianceOfficer, Examiner |
| POST | `/hmda/applications` | Open a register record at the intake stage | LoanOfficer |
| PATCH | `/hmda/applications/{id}` | Capture or amend register fields at the current stage | LoanOfficer |
| GET | `/hmda/applications/{id}` | Read one register record with both state dimensions | SystemAdmin, InstitutionAdmin, ComplianceAnalyst, ComplianceOfficer, LoanOfficer, Examiner |
| POST | `/hmda/applications/{id}/advance` | Move the record to the next field-capture stage | LoanOfficer |
| POST | `/hmda/applications/{id}/action-taken` | Record the action taken and its date, plus the fields that only become applicable once the action is known | LoanOfficer |
| POST | `/hmda/applications/{id}/reopen` | Unlock a locked record for correction; drives the five-hop decertification cascade | ComplianceAnalyst |
| GET | `/hmda/applications/{id}/corrections` | List records that supersede this one | SystemAdmin, InstitutionAdmin, ComplianceAnalyst, ComplianceOfficer, LoanOfficer, Examiner |
| GET | `/hmda/applications/{id}/demographic-entries` | List the record's applicants; filterable by `applicant_role` | SystemAdmin, InstitutionAdmin, ComplianceAnalyst, ComplianceOfficer, LoanOfficer, Examiner |
| GET | `/hmda/applications/{id}/geocode-assignments` | List the record's geocode attempts, newest last; filterable by `is_current` | SystemAdmin, InstitutionAdmin, ComplianceAnalyst, ComplianceOfficer, LoanOfficer, Examiner |
| GET | `/hmda/applications/{id}/edit-exceptions` | List every exception ever raised against this record; filterable by `status` and by `severity` | SystemAdmin, InstitutionAdmin, ComplianceAnalyst, ComplianceOfficer, LoanOfficer, Examiner |
| GET | `/hmda/applications/{id}/audit-findings` | List scrub findings raised against this record; filterable by `resolution` | SystemAdmin, InstitutionAdmin, ComplianceAnalyst, ComplianceOfficer, Examiner |
| POST | `/hmda/demographic-entries` | Record ethnicity, race and sex for one applicant on a register record | LoanOfficer |
| PATCH | `/hmda/demographic-entries/{id}` | Amend a recorded applicant's demographic data; all collection rules are re-evaluated on the merged row | LoanOfficer |
| POST | `/hmda/geocode-assignments` | Geocode the secured property and assign a census tract; supersedes the record's previous current assignment | LoanOfficer |
| POST | `/hmda/geocode-assignments/{id}/manual-override` | Analyst pins a census tract for an ambiguous or unmatched assignment | ComplianceAnalyst |
| POST | `/hmda/edit-runs` | Run the syntactical, validity, quality and macro edit battery over the institution's register snapshot | ComplianceAnalyst |
| GET | `/hmda/edit-runs/{id}` | Read one edit run with its full exception ledger | SystemAdmin, InstitutionAdmin, ComplianceAnalyst, ComplianceOfficer, Examiner |
| GET | `/hmda/edit-runs/{id}/exceptions` | List the run's exceptions in creation order; filterable by `status` and by `severity` | SystemAdmin, InstitutionAdmin, ComplianceAnalyst, ComplianceOfficer, Examiner |
| GET | `/hmda/edit-runs/{id}/submissions` | List submissions attached to this run | SystemAdmin, InstitutionAdmin, ComplianceAnalyst, ComplianceOfficer, Examiner |
| POST | `/hmda/edit-exceptions/{id}/verify` | Analyst verifies a quality or macro exception as reviewed-and-correct | ComplianceAnalyst |
| POST | `/hmda/submissions` | Open a filing submission for the institution's activity year; supersedes any existing draft submission | ComplianceOfficer |
| GET | `/hmda/submissions/{id}` | Read one filing submission | SystemAdmin, InstitutionAdmin, ComplianceAnalyst, ComplianceOfficer, Examiner |
| POST | `/hmda/submissions/{id}/attach-edit-run` | Bind a completed edit run to the submission | ComplianceOfficer |
| POST | `/hmda/submissions/{id}/certify` | Officer attests to the register; freezes the final record count and locks the institution for filing | ComplianceOfficer |
| POST | `/hmda/submissions/{id}/file` | File the register with the regulator; evaluates the annual deadline and publishes the disclosure statements | ComplianceOfficer |
| POST | `/hmda/submissions/{id}/review` | Examiner accepts or rejects a filed submission | Examiner |
| POST | `/hmda/submissions/{id}/resubmit` | Return a rejected submission to draft so the register can be corrected and refiled | ComplianceOfficer |
| GET | `/hmda/submissions/{id}/disclosure-statements` | List the public artifacts produced by this filing; filterable by `statement_type` | SystemAdmin, InstitutionAdmin, ComplianceAnalyst, ComplianceOfficer, Examiner |
| POST | `/hmda/audit-samples` | Draw a scrub sample over a closed action-date period | ComplianceAnalyst |
| GET | `/hmda/audit-samples/{id}` | Read one audit sample with its selection and defect counters | SystemAdmin, InstitutionAdmin, ComplianceAnalyst, ComplianceOfficer, Examiner |
| GET | `/hmda/audit-samples/{id}/findings` | List the sample's findings; filterable by `resolution` | SystemAdmin, InstitutionAdmin, ComplianceAnalyst, ComplianceOfficer, Examiner |
| POST | `/hmda/audit-findings` | Record one re-keyed field comparison against a sampled record | ComplianceAnalyst |
| POST | `/hmda/audit-samples/{id}/close` | Close the sample, choosing which defect-rate variant to publish | ComplianceAnalyst |
| POST | `/hmda/fair-lending-analyses` | Compute a denial-rate disparity index between a control and a protected group using register data | ComplianceAnalyst |
| POST | `/_clock/set_current_utc` | Set the server's logical clock to the supplied `to_iso8601` instant | SystemAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_INSTITUTION_SCOPE_VIOLATION` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_INSTITUTION_NOT_FOUND` | 404 |
| `ERR_APPLICATION_NOT_FOUND` | 404 |
| `ERR_DEMOGRAPHIC_ENTRY_NOT_FOUND` | 404 |
| `ERR_GEOCODE_ASSIGNMENT_NOT_FOUND` | 404 |
| `ERR_CENSUS_TRACT_NOT_FOUND` | 404 |
| `ERR_EDIT_RUN_NOT_FOUND` | 404 |
| `ERR_EDIT_EXCEPTION_NOT_FOUND` | 404 |
| `ERR_SUBMISSION_NOT_FOUND` | 404 |
| `ERR_AUDIT_SAMPLE_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STALE_INSTITUTION_VERSION` | 412 |
| `ERR_STALE_APPLICATION_VERSION` | 412 |
| `ERR_INVALID_STAGE_TRANSITION` | 409 |
| `ERR_INVALID_SUBMISSION_STATE` | 409 |
| `ERR_EXCEPTION_NOT_OPEN` | 409 |
| `ERR_GEOCODE_NOT_OVERRIDABLE` | 409 |
| `ERR_SAMPLE_NOT_OPEN` | 409 |
| `ERR_APPLICATION_ARCHIVED` | 409 |
| `ERR_EDIT_RUN_INVALIDATED` | 409 |
| `ERR_GEOCODE_UNRESOLVED` | 409 |
| `ERR_MISSING_APPLICANT_DEMOGRAPHICS` | 409 |
| `ERR_VISUAL_OBSERVATION_NOT_PERMITTED` | 422 |
| `ERR_DISAGGREGATED_CODE_NOT_PERMITTED` | 422 |
| `ERR_OBSERVATION_REQUIRED_FOR_IN_PERSON` | 422 |
| `ERR_NON_NATURAL_PERSON_MISMATCH` | 422 |
| `ERR_DENIAL_REASON_REQUIRED` | 422 |
| `ERR_DENIAL_REASON_NOT_PERMITTED` | 422 |
| `ERR_PURCHASER_TYPE_REQUIRED` | 422 |
| `ERR_GEOCODE_TRACT_MISMATCH` | 422 |
| `ERR_EDIT_RUN_INSTITUTION_MISMATCH` | 422 |
| `ERR_FINDING_APPLICATION_NOT_IN_SAMPLE` | 422 |
| `ERR_ACTION_DATE_BEFORE_APPLICATION` | 422 |
| `ERR_ACTION_DATE_IN_FUTURE` | 422 |
| `ERR_ACTION_DATE_OUTSIDE_ACTIVITY_YEAR` | 422 |
| `ERR_INVALID_WINDOW` | 422 |
| `ERR_EDIT_RUN_WINDOW_OVERLAP` | 409 |
| `ERR_REMEDIATION_WINDOW_OVERLAP` | 409 |
| `ERR_DUPLICATE_ULI` | 409 |
| `ERR_DUPLICATE_LEI` | 409 |
| `ERR_DUPLICATE_DEMOGRAPHIC_ROLE` | 409 |
| `ERR_TOO_MANY_RACE_CODES` | 422 |
| `ERR_SEVERITY_NOT_VERIFIABLE` | 422 |
| `ERR_OPEN_VALIDITY_EDITS` | 422 |
| `ERR_VERIFICATION_QUOTA_NOT_MET` | 422 |
| `ERR_EMPTY_SAMPLE_POPULATION` | 422 |
| `ERR_EMPTY_CONTROL_GROUP` | 422 |
