# Tenant Screening API — Product Requirements Document

## 1. Introduction

Tenant screening is a regulated consumer-reporting business. A landlord who orders a background check is making a credit-adjacent decision about a person's housing, and every step of that decision — consent, identity proofing, which public records may legally be surfaced in which state, how income is counted when a housing voucher is involved, what happens when the landlord says no — carries statutory obligations in the style of the Fair Credit Reporting Act and state fair-housing law. This document specifies the Tenant Screening API, the operating platform of a tenant screening bureau that serves landlords and property managers end to end: application intake and identity verification, credit, eviction, and criminal record searches constrained by per-state jurisdictional rules, income verification with rent-to-income scoring, a recommendation engine, the landlord's decision, adverse action notices with grounded reason codes, and a full dispute-and-reinvestigation loop with correction cascades.

The bureau's operating model adds several second-order obligations beyond the happy path. Source-of-income protections change how affordability is computed for voucher holders; some jurisdictions forbid criminal searches or cap screening fees outright; some require landlords to accept portable screening reports the applicant already paid for elsewhere. Co-signers and guarantors are evaluated under one of two qualification policies pinned by the landlord's published screening criteria, and those criteria must be disclosed to applicants and applied consistently — which is why the platform also produces consistency audit runs comparing what the bureau recommended against what the landlord actually decided. All time-dependent rules in the system read a single logical clock rather than wall-clock time, and every endpoint is mounted under the `/api` prefix.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring their operational capacity. A request missing either header, or presenting a malformed one, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. The system recognizes four roles, spelled exactly as follows: `ComplianceAdmin`, `Screener`, `Landlord`, and `Applicant`. Each operation admits a specific set of roles (enumerated per endpoint in §4); a caller whose role is not admitted is rejected with `ERR_UNAUTHORIZED_ROLE`.

Two of the roles are entity-backed. When `X-User-Role` is `Landlord`, `X-User-ID` is the `id` of the acting Landlord record; ownership checks on any resource that references a landlord — criteria sets, applications, guarantors, adverse action notices — compare the resource's `landlord_id` field to `X-User-ID`, and a mismatch is rejected with `ERR_OWNERSHIP_MISMATCH`. When `X-User-Role` is `Applicant`, `X-User-ID` is the `id` of the acting Applicant record; ownership checks on consumer-facing actions such as consent, withdrawal, and dispute filing compare the owning application's `applicant_id` to `X-User-ID`, again surfacing `ERR_OWNERSHIP_MISMATCH` on a mismatch. Reads obey the same scoping. A `Landlord` caller is scoped to their own landlord record and to every resource that references their `landlord_id` or hangs off one of their applications — criteria sets, applications, reports, records, guarantors, income verifications, adverse action notices, disputes, and their own consistency-audit history. An `Applicant` caller is scoped to their own applications and the resources hanging off them — reports, records, guarantors, income verifications, notices, and disputes; `Applicant` reads of bureau-wide configuration and disclosure resources — jurisdiction rules, criteria sets, landlord records, and landlords' consistency-audit histories — are unrestricted.

The remaining two roles are opaque. When `X-User-Role` is `ComplianceAdmin` or `Screener`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity, and reads for these roles are unrestricted. The server may still record it where a workflow writes it — for example as a report's `originating_screener_id` when a screener runs a search, or as a dispute's `reinvestigator_screener_id` when reinvestigation opens — and it is compared against itself for segregation-of-duties checks, but it is never compared to any entity's `id` for ownership purposes.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, taken from the server's wall clock at response time; the envelope timestamp is the one timestamp in the system not driven by the logical clock of §2.4.
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
- Requests to an undefined path, or to a defined path with an unsupported method, are answered in the same error envelope with `ERR_NOT_FOUND` (HTTP 404).

---

### 2.3. Pagination

List endpoints paginate through two query parameters. The `limit` parameter sets the maximum number of items returned: it defaults to 10, accepts a minimum of 1, and is capped at a maximum of 100 — a `limit` or `offset` that is not an integer, a `limit` below 1 or above 100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` rather than clamped. The `offset` parameter sets how many items are skipped and defaults to 0. Unless a subsection states otherwise, every list is returned sorted by creation timestamp (`created_at`) in ascending order with ties broken by insertion order, and list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope, where `total_count` is the full count of items after filters and ownership scoping but before pagination, and `has_more` is true exactly when `offset` plus the number of items in the returned page is less than `total_count`.

Most list endpoints also accept resource-specific filters (for example, applications can be filtered by `landlord_id`, `applicant_id`, `criteria_id`, `portable_report_id`, or `status`); those filters compose with pagination, and for entity-backed callers the ownership scoping of §2.1 applies on top of any filter supplied.

### 2.4. The Logical Clock

Every time-dependent rule in this document — effective windows, lookback cutoffs, dispute and reinvestigation deadlines, portable-report validity, and every stamped timestamp — reads a single server-side **logical clock**, never the wall clock. At server startup, before any adjustment, the logical clock reads `2026-08-01T00:00:00Z`; it never falls back to wall-clock time under any circumstance. A `ComplianceAdmin`-only test-driving capability sets the clock to a supplied `to_iso8601` instant, and the response echoes the newly installed time as `current_utc`. Workflow prose below refers to "the clock"; it always means this logical clock.

### 2.5. Common Resource Properties

Every primary resource carries a standard set of system-managed fields:

- `id` (string): a server-minted unique identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on any mutation of the resource.
- `version` (integer): a system-managed integer that starts at 1 on creation and increments by one with every modification, and that anchors optimistic concurrency control where §2.8 applies. The suppression classification of §3.4 is a separate mutation applied immediately after a screening record's creation, so a freshly created record is first observable with `version` 2.

Every datetime-valued field in a response is serialized in this same representation — an ISO 8601 UTC timestamp with three fractional digits and a `Z` suffix — not just the common `created_at` and `updated_at`. The uniform format covers lifecycle event stamps and computed deadlines (`consent_signed_at`, `submitted_at`, `published_at`, `delivered_at`, `last_delivered_at`, `decided_at`, `suspended_at`, `issued_at`, `dispute_deadline`, `filed_at`, `reinvestigation_deadline`, `resolved_at`, `rescinded_at`, `run_at`), echoed effective-window endpoints (`effective_from`, `effective_to`), stored date fields (`dob`, `record_date`), and the clock endpoint's `current_utc` echo; a stamp written at server startup therefore reads `2026-08-01T00:00:00.000Z`.

One resource deliberately breaks this pattern: the **ConsistencyAuditRun** is an immutable event record carrying only `id` and `created_at`. It has no `updated_at` and no `version`, because an audit run is never modified after it is written.

A recurring convention applies to lifecycle timestamps and outcome fields: fields that record an event or a computed outcome are null until that event occurs. A landlord's `suspended_at` is null while the landlord is `ACTIVE`; a criteria set's `published_at` is null until publication; an application's `consent_signed_at`, `submitted_at`, `credit_score`, `verified_income_cents`, `affordability_passes`, `eviction_included_count`, `criminal_included_count`, `recommendation`, `decision`, and `decided_at` are null until consent, submission, search, and scoring or decision respectively supply them, and its `requires_reconsideration` flag begins as false; a report's `delivered_at` and `last_delivered_at` are null until first delivery; a record's `suppression_reason` is null unless the record is `SUPPRESSED`; a notice's `issued_at`, `dispute_deadline`, and `rescinded_at` are null until issue and rescission; and a dispute's `reinvestigator_screener_id`, `resolved_at`, and `resolution_notes` are null until reinvestigation and resolution.

All mutations in the system are atomic and immediately visible: when an operation cascades across several resources — a dispute flips records and its parent report, a suspension cancels a portfolio of applications — every affected resource reflects its new state in the same response cycle, with each mutated resource refreshing `updated_at` and incrementing `version` as described above.

### 2.6. Request Validation Order

Every request is validated through a fixed pipeline, and the pipeline's order is normative: an earlier stage's failure masks every later stage. The stages, evaluated in order, are:

1. **Header presence and form.** `X-User-ID` and `X-User-Role` must be present and well-formed, failing with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Request-body malformation — a missing required field, a type mismatch, an out-of-range scalar — fails with `ERR_INVALID_REQUEST` (HTTP 400), evaluated at the point the operation first consumes the payload: always after the header and role stages, and after any existence, ownership, from-state, or compliance checks the endpoint performs before reading the body. Unrecognized body fields are ignored.
2. **Role admission.** The role in `X-User-Role` must be admitted on the endpoint per §4, failing with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).
3. **Existence.** Resource identifiers in the path are validated left to right, and then identifiers referenced in the body (such as `applicant_id` or `portable_report_id`); the first missing resource fails the request with `ERR_NOT_FOUND` (HTTP 404). A request targeting a child under a non-existent parent therefore reports the parent first.
4. **Ownership.** For entity-backed callers, the resource must belong to the caller per §2.1, failing with `ERR_OWNERSHIP_MISMATCH` (HTTP 403). `ComplianceAdmin` and `Screener` callers skip this stage.
5. **Optimistic concurrency.** Where §2.8 applies, the carried version must match the parent's current `version`, failing with `ERR_STALE_VERSION` (HTTP 412).
6. **Resource from-state.** The target resource must be in the state the operation requires. Terminal applications fail with `ERR_APPLICATION_TERMINAL`; other wrong states fail with the resource's own state error (`ERR_INVALID_APPLICATION_STATE`, `ERR_INVALID_CRITERIA_STATE`, `ERR_INVALID_REPORT_STATE`, `ERR_INVALID_DISPUTE_STATE`, `ERR_INVALID_INCOME_VERIFICATION_STATE`, `ERR_INVALID_GUARANTOR_STATE`, or `ERR_INVALID_NOTICE_STATE`), all HTTP 409. Running a bureau search on a portable application is also rejected at this stage with `ERR_PORTABLE_SEARCH_FORBIDDEN` (HTTP 409).
7. **Cross-entity state.** Operations that depend on a related resource's state are checked here: the landlord must be `ACTIVE` when applications are created (`ERR_LANDLORD_SUSPENDED`); scoring requires the application's income verification resolved (`ERR_INCOME_VERIFICATION_UNRESOLVED`); a decision requires the report `DELIVERED` or `RE_DELIVERED` (`ERR_INVALID_REPORT_STATE`); guarantor and income-verification creation and guarantor evaluation require a non-terminal application (`ERR_APPLICATION_TERMINAL`). All are HTTP 409.
8. **Compliance gates**, evaluated in their own pinned relative order: applicant consent before any bureau search (`ERR_CONSENT_REQUIRED`), verified identity before any bureau search (`ERR_IDENTITY_NOT_VERIFIED`), the reinvestigating screener differing from the report's originator (`ERR_SEGREGATION_OF_DUTIES`, HTTP 403), the resolver being the assigned reinvestigator (`ERR_NOT_REINVESTIGATOR`, HTTP 403), and adverse-action reason codes being non-empty and grounded (`ERR_UNGROUNDED_ADVERSE_REASON`). Except where noted these are HTTP 422.
9. **Clock-relative windows.** Temporal gates fail with `ERR_DISPUTE_WINDOW_CLOSED`, `ERR_PORTABLE_REPORT_EXPIRED`, or `ERR_REINVESTIGATION_OVERDUE` (all HTTP 422), per the window rules in §3.
10. **Structural constraints.** `ERR_RULE_WINDOW_OVERLAP`, `ERR_CRITERIA_WINDOW_OVERLAP`, `ERR_INCOME_VERIFICATION_EXISTS`, `ERR_NO_PUBLISHED_CRITERIA`, and `ERR_IDENTITY_ATTEMPTS_EXHAUSTED` (HTTP 409), together with `ERR_PORTABLE_REPORT_INVALID` and `ERR_PORTABLE_REPORT_NOT_ACCEPTED` (HTTP 422), are evaluated at this stage; §3 states each rule next to its workflow.
11. **Referential integrity of dispute payloads.** Every id in a dispute's `disputed_record_ids` must belong to the dispute's report, failing with `ERR_RECORD_NOT_ON_REPORT` (HTTP 422).
12. **Fiscal rules never reject.** There are no blocking fiscal validations: a jurisdiction's fee cap is applied as a ceiling inside the fee calculation, never as a rejection of the request.

### 2.7. Money, Rounding, and the Screening Fee Ledger

All monetary values in the system are integer cents — rents, incomes, voucher amounts, fees, caps, and balances are never fractional. Wherever a multiplication produces a fractional cent (an income multiple applied to a rent, a surcharge rate applied to a base fee), the product is rounded half-up to integer cents, and the order of rounding stated with each calculation is normative. The one non-integer numeric in the system is the audit `deviation_rate`, which is computed to four decimal places, also rounding half-up.

Each Landlord carries a running ledger, `fee_balance_cents`, which starts at zero. Screening fees are added to it when a bureau record search runs and when a portable application is submitted; refunds are subtracted from it when an application is withdrawn or its landlord is suspended before delivery (§3.7). The per-application `fee_charged_cents` is a historical record of what was charged and is never decremented by refunds, so the pair of fields always allows the charge-and-refund history to be reconstructed.

### 2.8. Optimistic Concurrency Control on Criteria Publication

Exactly one operation in the system is guarded by optimistic concurrency control: publishing a screening criteria set. A publish request must carry `expected_landlord_version`, a non-optional field holding the landlord `version` the client last observed. Because the window-conflict evaluation must run against the landlord's latest criteria set, and because every successful publish advances the landlord's `version` by one, a publish carrying a previously observed version is acting on a stale view of that set: if `expected_landlord_version` does not match the landlord's current `version`, the publish is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint accepts a version field; all other mutations proceed without an OCC check.

## 3. Business Logic & Workflows

### 3.1. Bureau Setup: Landlords, Jurisdiction Rules, and Screening Criteria

Before any screening can occur, a `ComplianceAdmin` enrolls the bureau's client by creating a **Landlord** with the client's legal `name` and a billing `contact_email`. New landlords begin with `status` `ACTIVE`, a `fee_balance_cents` of zero, and `version` 1. Reading a landlord back returns both the current `version` (needed for the publish protocol of §2.8) and the live `fee_balance_cents` ledger.

Jurisdictional compliance is configured through **JurisdictionRule** records. A `ComplianceAdmin` creates each rule with the two-letter `state_code` it governs; the `criminal_lookback_years` and `eviction_lookback_years`, each zero or greater, beyond which records of that type are suppressed (a criminal lookback of zero prohibits the criminal search in that state entirely); the fair-housing flags `source_of_income_protected` (which switches affordability scoring to the source-of-income variant of §3.6) and `portable_report_acceptance_required` (which obliges landlords to honor portable reports); an optional fee cap `max_screening_fee_cents`, where an omitted or null value means the jurisdiction imposes no cap; and a half-open effective window in which `effective_from` is inclusive, `effective_to` is exclusive, and an omitted or null `effective_to` leaves the rule open-ended. Two rules for the same `state_code` may touch — one rule's `effective_to` equal to the other's `effective_from` is legal adjacency — but their windows may never overlap; a violating creation is rejected with `ERR_RULE_WINDOW_OVERLAP`. Rules can be listed with an optional `state_code` filter.

Each landlord authors one or more **ScreeningCriteria** sets, the public statement of their rental standards. Creation captures a `name` for the set, the `disclosure_summary` shown to applicants as the criteria-disclosure document, the inclusive `min_credit_score` floor, the required `income_multiplier` (a number such as 3.0, meaning verified income must reach three times the monthly rent), the `guarantor_policy` of `INDEPENDENT_ONLY` or `COMBINED_ALLOWED`, the `guarantor_income_multiplier` used by the independent variant (a number such as 4.0), the acceptance flags `accepts_portable_reports` and `accepts_voucher_income`, and a closed effective window in which both `effective_from` and `effective_to` are inclusive and an omitted or null `effective_to` is open-ended. The set's `landlord_id` is taken from the acting landlord's `X-User-ID` — an acting landlord id with no Landlord record fails with `ERR_NOT_FOUND` — its `status` begins as `DRAFT`, and `published_at` stays null until publication.

Publication moves a `DRAFT` set to `PUBLISHED` — attempting it from any other state fails with `ERR_INVALID_CRITERIA_STATE` — and is the OCC-guarded operation of §2.8, carrying the mandatory `expected_landlord_version`. Beyond the version check, publication enforces window hygiene: the set's closed effective window must not overlap the closed window of any other `PUBLISHED` set belonging to the same landlord, and because both endpoints of a closed window are inclusive, two sets whose windows merely touch at an endpoint are in conflict; violations are rejected with `ERR_CRITERIA_WINDOW_OVERLAP`. A successful publish stamps `published_at` with the clock and increments the landlord's `version` by one. A set in `DRAFT` or `PUBLISHED` may instead be archived to `ARCHIVED` (from any other state, `ERR_INVALID_CRITERIA_STATE`); archiving does not disturb applications already pinned to the set, which continue to be evaluated against it. Criteria can be listed with optional `landlord_id` and `status` filters, and a single set can be fetched as the disclosure document shown to applicants.

### 3.2. Applicant Intake, Consent, and Identity Verification

Intake begins when a `Screener` registers an **Applicant** with the consumer's `full_name`, date of birth `dob`, contact `email`, `ssn_last4` (exactly four digits), and two-letter `residence_state`.

A `Landlord` then opens a **ScreeningApplication** by naming the `applicant_id`, the two-letter `unit_state_code` of the rental unit (which drives all jurisdictional behavior for the file), the `monthly_rent_cents` (must be positive), the applicant-declared `stated_monthly_income_cents` (may not be negative), and optionally a `voucher_monthly_amount_cents` (the monthly voucher or subsidy amount, defaulting to zero) and a `portable_report_id` for portable reuse (§3.3). The acting landlord id must resolve to a Landlord record, failing with `ERR_NOT_FOUND` otherwise, and the landlord must be `ACTIVE`; attempts to open applications for a `SUSPENDED` landlord are rejected with `ERR_LANDLORD_SUSPENDED`. The application's `landlord_id` is taken from the caller's `X-User-ID`; `status` begins as `DRAFT`; the parallel identity dimension `identity_status` begins as `UNVERIFIED` with `identity_attempts` at zero; `fee_charged_cents` begins at zero; and `consent_signed_at`, `submitted_at`, and `criteria_id` remain null. Malformed intake payloads — a missing required field, a type mismatch, an out-of-range scalar such as a non-positive rent or an `ssn_last4` that is not exactly four digits — fail with `ERR_INVALID_REQUEST`.

Federal-style consent is captured when the owning `Applicant` signs the screening consent, at which point the system stamps `consent_signed_at` with the clock. Consent on a terminal application is rejected with `ERR_APPLICATION_TERMINAL`; re-signing an already-signed application is permitted and re-stamps `consent_signed_at`. No bureau record search may run before this signature exists (§3.4).

Identity verification runs on its own state dimension, independent of the application's main `status`, and is never advanced by it. A `Screener` submits an attempt carrying a verification `method` and an `evidence_score`, but only while the application is `DRAFT` or `SUBMITTED`: attempts against `SCREENING` or `SCORED` applications are rejected with `ERR_INVALID_APPLICATION_STATE`, and terminal applications with `ERR_APPLICATION_TERMINAL`. Once `identity_attempts` has reached three, further attempts are rejected with `ERR_IDENTITY_ATTEMPTS_EXHAUSTED` before the evidence is even scored. Otherwise the attempt increments `identity_attempts` by one and the score is compared against the pass threshold of 70: an `evidence_score` of at least 70 — exactly 70 verifies, the boundary is inclusive — moves `identity_status` from `UNVERIFIED` or `FAILED` to `VERIFIED`, while anything below 70 moves it to (or keeps it in) `FAILED`, permitting a retry loop until attempts run out. `VERIFIED` is terminal for this dimension: any further attempt against a verified application is rejected with `ERR_INVALID_APPLICATION_STATE`.

### 3.3. Submission, Criteria Pinning, and Portable Screening Reports

Submission by the owning `Landlord` moves a `DRAFT` application to `SUBMITTED`; from any other non-terminal state the attempt fails with `ERR_INVALID_APPLICATION_STATE`, and from a terminal state with `ERR_APPLICATION_TERMINAL`. Within those bounds, the remaining checks fire in the pipeline order of §2.6. When a `portable_report_id` was supplied at creation, that report's existence is confirmed at the existence stage (`ERR_NOT_FOUND`). The temporal gate follows: the submission clock must be no later than the source report's `last_delivered_at` plus thirty days — the comparison is inclusive, so a submission landing exactly on the thirtieth day is accepted — and a report older than that is rejected with `ERR_PORTABLE_REPORT_EXPIRED`. A source report that has never been delivered has no `last_delivered_at` to measure the window against; it is not treated as expired but as invalid, and is rejected at the structural stage with `ERR_PORTABLE_REPORT_INVALID`. Finally the structural checks, in this relative order: exactly one `PUBLISHED` criteria set of this landlord must have a closed effective window containing the submission clock, otherwise `ERR_NO_PUBLISHED_CRITERIA`; the portable report must belong to the same consumer (its application's `applicant_id` equals this application's) and must be `DELIVERED` or `RE_DELIVERED`, otherwise `ERR_PORTABLE_REPORT_INVALID`; and portable acceptance must hold, meaning either the jurisdiction rule covering `unit_state_code` mandates `portable_report_acceptance_required` or the pinned criteria's `accepts_portable_reports` is true, otherwise `ERR_PORTABLE_REPORT_NOT_ACCEPTED`.

A successful submission pins `criteria_id` to the selected `PUBLISHED` set and stamps `submitted_at` with the clock; that pinned set governs every later threshold on the file, even if it is subsequently archived. When no `portable_report_id` is involved, that is the whole of the transition, and the file waits for the bureau search of §3.4.

Portable submissions do considerably more. Rather than ordering a fresh search, the system creates a new **ScreeningReport** as a copy of the source: `is_portable_copy` set to true, `source_report_id` pointing back at the submitted report, `status` `DRAFT`, the source report's screening records copied over, and the suppression sweep of §3.4 re-run against this application's `unit_state_code` at the submission clock — so records lawful in the source state may be suppressed here, or vice versa. The copy inherits `originating_screener_id` from the source report and carries the source's `credit_score`. The application is charged the portable flat fee of 1000 cents (ten dollars): `fee_charged_cents` is set to 1000 and the landlord's `fee_balance_cents` increases by the same amount, with no surcharges and no jurisdictional cap applied. On original reports — those produced by a live bureau search — `is_portable_copy` is false and `source_report_id` is null.

### 3.4. The Bureau Search: Records, Suppression, and the Screening Fee

The core bureau operation is the record search, performed by a `Screener` on a `SUBMITTED` application and advancing it to `SCREENING`. Its guards fire in pipeline order: a terminal application yields `ERR_APPLICATION_TERMINAL` and any other wrong state `ERR_INVALID_APPLICATION_STATE`; an application submitted with a `portable_report_id` is rejected with `ERR_PORTABLE_SEARCH_FORBIDDEN`, because portable files reuse their copied report and never run a fresh search; then the two compliance gates — consent first, so a null `consent_signed_at` is rejected with `ERR_CONSENT_REQUIRED`, and only then identity, so an `identity_status` short of `VERIFIED` is rejected with `ERR_IDENTITY_NOT_VERIFIED`.

The request carries the bureau feed: a `credit_score` and a `records` array whose entries each describe one public record with a `record_type` of `EVICTION` or `CRIMINAL`, the `jurisdiction_state_code` where the record was filed, the filing `record_date`, and a free-text `description`. The system creates the ScreeningReport in `DRAFT`, writing the caller's `X-User-ID` as `originating_screener_id` and the feed's score as the report's `credit_score`, then creates one **ScreeningRecord** per input entry, preserving the input array order; record listings preserve that same creation sequence and accept an optional `report_id` filter.

Immediately upon creation, the suppression sweep classifies every record. The covering rule is the JurisdictionRule whose `state_code` equals the application's `unit_state_code` and whose half-open window contains the current clock — `effective_from` at or before the clock and `effective_to` after it, a null end treated as open-ended. When no rule covers the state, default lookbacks of seven years apply to both record types and criminal searching is treated as allowed. Each record is then classified: a `CRIMINAL` record in a state whose `criminal_lookback_years` is zero becomes `SUPPRESSED` with `suppression_reason` `SEARCH_PROHIBITED`; otherwise, any record whose `record_date` is strictly earlier than the cutoff — the calendar date of the clock minus the lookback years for its record type (a February 29 clock date maps to February 28 when the target year is not a leap year) — becomes `SUPPRESSED` with `suppression_reason` `LOOKBACK_EXPIRED`; every remaining record is `INCLUDED`. The boundary is pinned as strictly-older-than: a record dated exactly on its cutoff date stays `INCLUDED`. `suppression_reason` is null on any record that is not `SUPPRESSED`. Throughout the report's life, `included_record_count` is an invariant equal to the number of its records in `INCLUDED` status, recomputed whenever record statuses change.

The search also fixes the screening fee. The executed search types are credit (always), eviction (always), and criminal (only when the covering rule's `criminal_lookback_years` is above zero — a prohibited criminal search is not executed and is not charged). The fee starts from a base of 2500 cents (twenty-five dollars), and each executed search type adds a surcharge equal to 0.125 times the base fee. The rounding order is normative: each per-type surcharge is rounded half-up to integer cents first — 313 cents per type — then the base and the rounded surcharges are summed, and only then is any cap applied. Summing the raw fractional surcharges and rounding once at the end is non-conformant: for a full three-type search that shortcut yields 3438 cents, while the pinned order yields 3439. When the covering rule carries a non-null `max_screening_fee_cents`, the charged fee is the lesser of the cap and the computed fee, and the cap binds inclusively — a computed fee exactly equal to the cap charges the cap. The resulting fee is added both to the application's `fee_charged_cents` and to the landlord's `fee_balance_cents`.

### 3.5. Income Verification and Guarantor Evaluation

A `Screener` opens an **IncomeVerification** for an application by naming the `employer_name` being verified, provided the application is non-terminal (a terminal application rejects with `ERR_APPLICATION_TERMINAL`). At most one income verification may exist per application — a second attempt to start one fails with `ERR_INCOME_VERIFICATION_EXISTS` — and a new verification starts as `PENDING`.

Resolving a verification requires it to be `PENDING` (otherwise `ERR_INVALID_INCOME_VERIFICATION_STATE`) and takes an `outcome`: resolving as `VERIFIED` records the `verified_monthly_income_cents`, while resolving as `FAILED` records the `failure_reason`. A failed verification is not final: retrying moves it from `FAILED` back to `PENDING`, clearing both the `failure_reason` and any `verified_monthly_income_cents` to null. `VERIFIED` is terminal for the verification. Verifications can be listed with an optional `application_id` filter.

Guarantors and co-signers follow a parallel track. The owning `Landlord` attaches a **Guarantor** to a non-terminal application (terminal ones reject with `ERR_APPLICATION_TERMINAL`) by providing the guarantor's `full_name` and declared `stated_monthly_income_cents`; the record starts as `PENDING`, with its verified fields null until evaluation. Evaluation is a `Screener` operation supplying the guarantor's `verified_monthly_income_cents` and `credit_score`; it requires the guarantor to be `PENDING` (otherwise `ERR_INVALID_GUARANTOR_STATE`) and the application to be in `DRAFT`, `SUBMITTED`, `SCREENING`, or `SCORED` (a terminal application rejects with `ERR_APPLICATION_TERMINAL`). Which qualification rule applies is decided by the pinned criteria's `guarantor_policy`, and the variant actually applied is recorded on the guarantor as `qualification_policy_used`:

- Under `INDEPENDENT_ONLY`, the guarantor qualifies when their verified income alone reaches the product of the criteria's `guarantor_income_multiplier` and the application's `monthly_rent_cents`, rounded half-up to integer cents. The applicant's income is ignored entirely in this variant.
- Under `COMBINED_ALLOWED`, the applicant's verified income — the income verification's `verified_monthly_income_cents` when it is `VERIFIED`, and zero otherwise — is pooled with the guarantor's verified income, and the combined sum must reach the product of the criteria's ordinary `income_multiplier` and the `monthly_rent_cents`, rounded half-up to integer cents. Because the pooled threshold is the lower one, identical incomes can flip a guarantor from `DECLINED` under the independent variant to `APPROVED` under the combined one.

Both thresholds are inclusive: income exactly equal to the threshold qualifies. If the application has no pinned criteria set because it was never submitted, no qualification variant applies: the evaluation records a null `qualification_policy_used` and the guarantor is `DECLINED`. The guarantor's `credit_score` is recorded at evaluation time but plays no part in the qualification threshold. A qualifying evaluation sets the guarantor to `APPROVED`; otherwise to `DECLINED`. Guarantors can be listed with an optional `application_id` filter.

### 3.6. Scoring, Delivery, and the Landlord's Decision

Scoring is a `Screener` operation that moves a `SCREENING` application to `SCORED` (other non-terminal states yield `ERR_INVALID_APPLICATION_STATE`, terminal states `ERR_APPLICATION_TERMINAL`). It is gated on income: the application's income verification must exist and be resolved to `VERIFIED` or `FAILED` — a missing or still-`PENDING` verification rejects the score with `ERR_INCOME_VERIFICATION_UNRESOLVED`.

Scoring writes four snapshots onto the application. `verified_income_cents` copies the verification's `verified_monthly_income_cents`, and is null when the verification `FAILED`. `eviction_included_count` and `criminal_included_count` count the report's `INCLUDED` records of each type at score time. `affordability_passes` evaluates the rent-to-income rule:

- In the **standard variant**, the pass threshold is the pinned criteria's `income_multiplier` times the application's `monthly_rent_cents`, rounded half-up to integer cents; the application passes when `verified_income_cents` is not null and is at least the threshold — income exactly equal to the threshold passes.
- The **source-of-income-adjusted variant** applies when the covering jurisdiction rule's `source_of_income_protected` is true, the application carries a positive `voucher_monthly_amount_cents`, and the pinned criteria's `accepts_voucher_income` is true. Only the tenant's share of rent is tested: the applicable rent is `monthly_rent_cents` minus `voucher_monthly_amount_cents`, and when that difference is zero or negative, affordability passes automatically; otherwise the same multiplier threshold is applied to the reduced rent.

The `recommendation` is then read from a pinned decision table, evaluated in order with the first matching branch winning. First, a `credit_score` below the criteria's `min_credit_score` recommends denial. Second, any included evictions — `eviction_included_count` above zero — recommend denial. Third, any included criminal records — `criminal_included_count` above zero — recommend denial. Fourth, a passing affordability result recommends approval. Fifth, the existence of an `APPROVED` guarantor on the application recommends a conditional outcome. Anything else recommends denial. The emitted values are `RECOMMEND_DENY`, `RECOMMEND_APPROVE`, and `RECOMMEND_CONDITIONAL` respectively.

Delivery is what makes a report visible for decision. A `Screener` delivers a report from `DRAFT` to `DELIVERED`, allowed only while its application is `SCORED` — a report in any other state yields `ERR_INVALID_REPORT_STATE`, and an application in the wrong state yields `ERR_INVALID_APPLICATION_STATE` — stamping both `delivered_at` and `last_delivered_at` with the clock. The same delivery operation re-delivers an `AMENDED` report to `RE_DELIVERED`, allowed while the application is `SCORED`, `APPROVED`, or `DENIED`; re-delivery refreshes `last_delivered_at` while preserving the original `delivered_at`.

With a delivered report in hand, the owning `Landlord` records the `decision` — `APPROVE` or `DENY` — on a `SCORED` application whose report is `DELIVERED` or `RE_DELIVERED` (any other report state yields `ERR_INVALID_REPORT_STATE`). The application moves to `APPROVED` or `DENIED` accordingly, with `decided_at` stamped. A denial has a compliance side effect: the system creates an **AdverseActionNotice** in `DRAFT` whose `reason_codes` are derived in pinned order — `CREDIT_SCORE_BELOW_MINIMUM` when the application's `credit_score` is below the criteria's `min_credit_score`; `EVICTION_RECORD` when `eviction_included_count` is above zero; `CRIMINAL_RECORD` when `criminal_included_count` is above zero; `INCOME_UNVERIFIABLE` when the income verification `FAILED`; and `RENT_TO_INCOME_BELOW_REQUIRED` when `affordability_passes` is false and the income was `VERIFIED`.

Applications can be listed with optional `landlord_id`, `applicant_id`, `criteria_id`, `portable_report_id`, and `status` filters, with `Landlord` callers restricted to their own landlord scope and `Applicant` callers to their own applicant scope per §2.1. Reports can likewise be listed with `application_id` or `source_report_id` filters, and notices with an `application_id` filter.

### 3.7. Withdrawal, Suspension, and Fee Refunds

Either party to an application — the owning `Landlord` or the owning `Applicant` — may withdraw it while it is in `DRAFT`, `SUBMITTED`, `SCREENING`, or `SCORED`, optionally passing a `reason` (accepted but not persisted on the application); a terminal application rejects the withdrawal with `ERR_APPLICATION_TERMINAL`. Withdrawal moves the application to `WITHDRAWN` and cleans up in-flight work: a report still in `DRAFT` is `VOIDED`, and when `fee_charged_cents` is above zero and the application's report has never been delivered — `delivered_at` still null — the charged fee is refunded into the landlord's `fee_balance_cents`, so the charge and the refund net to zero. Reports already `DELIVERED`, `RE_DELIVERED`, `UNDER_DISPUTE`, or `AMENDED` keep their state, and a `VOIDED` report keeps its records' statuses but is excluded from portable-report reuse and from dispute eligibility.

Suspension is the administrative analogue, exercised by a `ComplianceAdmin` against the landlord rather than against any single file. The landlord's `status` becomes `SUSPENDED` and `suspended_at` is stamped with the clock. The suspension then cascades: every application belonging to that landlord that is still in `DRAFT`, `SUBMITTED`, `SCREENING`, or `SCORED` moves to `CANCELLED`, and each cancelled application receives the same cleanup as a withdrawal — its `DRAFT` report is `VOIDED`, and its `fee_charged_cents` is refunded into `fee_balance_cents` whenever its report was never delivered. As always, `fee_charged_cents` itself is a historical record and is never decremented by refunds. From the moment of suspension, any attempt to open a new application for that landlord is rejected with `ERR_LANDLORD_SUSPENDED`. Suspending an already-`SUSPENDED` landlord is a successful no-op: the landlord is returned unchanged, with no new `suspended_at` stamp and no repeated cascade.

### 3.8. Adverse Action Notices and Dispute Filing

Issuing an adverse action notice is the owning `Landlord`'s act and requires the notice to be in `DRAFT` (otherwise `ERR_INVALID_NOTICE_STATE`). The effective `reason_codes` are the request's override when one is provided, and the codes derived at decision time otherwise; in both cases the list must be non-empty and every code must be grounded in the application's current data. Grounding is checked per code: `CREDIT_SCORE_BELOW_MINIMUM` requires the `credit_score` to be below the criteria's `min_credit_score`; `EVICTION_RECORD` requires `eviction_included_count` above zero; `CRIMINAL_RECORD` requires `criminal_included_count` above zero; `INCOME_UNVERIFIABLE` requires a `FAILED` income verification; and `RENT_TO_INCOME_BELOW_REQUIRED` requires `affordability_passes` to be false with `VERIFIED` income. An empty or ungrounded list is rejected with `ERR_UNGROUNDED_ADVERSE_REASON`. Issuing stamps `issued_at` with the clock and computes `dispute_deadline` as thirty days after issue. An `ISSUED` notice may later be rescinded, moving it to `RESCINDED` and stamping `rescinded_at` — the expected response, for example, when a dispute correction flips the recommendation under a denial (§3.9).

The dispute channel is the consumer's challenge mechanism. The owning `Applicant` files a dispute against a report, which must be `DELIVERED` or `RE_DELIVERED` (any other report state yields `ERR_INVALID_REPORT_STATE`) and within the dispute window: the filing clock must be no later than the report's `last_delivered_at` plus thirty days, inclusive — filing exactly on the deadline day is allowed, and a later filing is rejected with `ERR_DISPUTE_WINDOW_CLOSED`. The filing names the challenged records as `disputed_record_ids` and a free-text `reason_text`; every id in the list must belong to this report, or the filing fails with `ERR_RECORD_NOT_ON_REPORT`. An empty `disputed_record_ids` list is accepted and disputes no records. A successful filing creates the **Dispute** in `FILED`, stamping `filed_at` with the clock and computing `reinvestigation_deadline` as thirty days from filing. The filing also cascades: the report moves from `DELIVERED` or `RE_DELIVERED` to `UNDER_DISPUTE`, every disputed record currently `INCLUDED` moves to `DISPUTED` (a named record in any other status keeps its status), and the report's `included_record_count` is recomputed. Second and later disputes against a `RE_DELIVERED` report re-enter the same loop. Disputes can be listed with optional `report_id` or `applicant_id` filters.

### 3.9. Reinvestigation, Correction Cascades, and Consistency Audits

Reinvestigation is opened by a `Screener` on a `FILED` dispute (any other state yields `ERR_INVALID_DISPUTE_STATE`), under a segregation-of-duties guard: the reinvestigating screener's `X-User-ID` must differ from the report's `originating_screener_id`, and a match is rejected with `ERR_SEGREGATION_OF_DUTIES`. Opening moves the dispute to `UNDER_REINVESTIGATION` and records the caller as `reinvestigator_screener_id`.

Resolving a dispute requires it to be `UNDER_REINVESTIGATION` (otherwise `ERR_INVALID_DISPUTE_STATE`), and only the recorded reinvestigator may resolve — any other screener is rejected with `ERR_NOT_REINVESTIGATOR`. The clock must be at or before the `reinvestigation_deadline`; exactly at the deadline is allowed, while a later resolution is rejected with `ERR_REINVESTIGATION_OVERDUE`. The resolver supplies an `outcome` and `resolution_notes`, and `resolved_at` is stamped with the clock. The two outcomes diverge sharply:

- An `UPHELD` resolution moves the dispute to `RESOLVED_UPHELD` and restores the status quo: every disputed record returns from `DISPUTED` to `INCLUDED`, the report moves from `UNDER_DISPUTE` to `RE_DELIVERED`, `included_record_count` is restored to its pre-dispute value, and `last_delivered_at` is refreshed to the clock, opening a fresh thirty-day dispute window.
- A `CORRECTED` resolution moves the dispute to `RESOLVED_CORRECTED` and cascades through three hops. First, every disputed record moves from `DISPUTED` to `REMOVED`, and the report moves from `UNDER_DISPUTE` to `AMENDED` with `included_record_count` recomputed. Second, the report's application re-runs the recommendation decision table of §3.6 with refreshed `eviction_included_count` and `criminal_included_count` snapshots, while `verified_income_cents` and `affordability_passes` keep their score-time values and are not recomputed. Third, when that re-run flips the recommendation away from `RECOMMEND_DENY` to `RECOMMEND_APPROVE` or `RECOMMEND_CONDITIONAL`, the application's `requires_reconsideration` flag is set to true. The recorded `decision` is not changed by the cascade; the landlord's recourse is to rescind the issued notice per §3.8.

The governance loop closes with the consistency audit. A `ComplianceAdmin` triggers an audit over one landlord's decided applications, and the system writes an immutable **ConsistencyAuditRun** — an event record carrying only `id` and `created_at`, with no `updated_at` and no `version` (§2.5). The run records the `landlord_id`, the `run_at` clock time, the `applications_examined` count (the landlord's applications in `APPROVED` or `DENIED`), the `inconsistencies_found` count, the `inconsistent_application_ids` array ordered by the applications' creation time ascending, and the `deviation_rate`. An application is inconsistent when its `decision` is `APPROVE` while its `recommendation` is `RECOMMEND_DENY`, or when its `decision` is `DENY` while its `recommendation` is `RECOMMEND_APPROVE`; a `RECOMMEND_CONDITIONAL` recommendation is consistent with either decision. The `deviation_rate` is `inconsistencies_found` divided by `applications_examined`, rounded half-up to four decimal places, and is zero when no applications were examined. A landlord's audit history can be listed back in creation order.

## 4. Endpoint Definitions

Operations that create a new resource — a landlord, jurisdiction rule, criteria set, applicant, application, guarantor, income verification, report (via record search), dispute, or audit run — return `201 Created`. Operations that act on an existing resource without creating a new one, including all state transitions, return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/_clock/set_current_utc` | Set the logical clock used by every time-dependent rule | ComplianceAdmin |
| POST | `/api/landlords` | Create a landlord (bureau client) | ComplianceAdmin |
| GET | `/api/landlords/{id}` | Get a landlord, including its OCC `version` and `fee_balance_cents` | ComplianceAdmin, Screener, Landlord, Applicant |
| POST | `/api/landlords/{id}/suspend` | Suspend a landlord; cancels non-terminal applications, voids their DRAFT reports, refunds undelivered fees | ComplianceAdmin |
| POST | `/api/jurisdiction-rules` | Create a jurisdiction rule; half-open windows per state must not overlap | ComplianceAdmin |
| GET | `/api/jurisdiction-rules` | List jurisdiction rules, optionally filtered by `state_code` | ComplianceAdmin, Screener, Landlord, Applicant |
| POST | `/api/criteria` | Create a screening criteria set in `DRAFT` | Landlord |
| GET | `/api/criteria` | List criteria, optionally filtered by `landlord_id` and/or `status` | ComplianceAdmin, Screener, Landlord, Applicant |
| GET | `/api/criteria/{id}` | Get one criteria set (the applicant-facing disclosure document) | ComplianceAdmin, Screener, Landlord, Applicant |
| POST | `/api/criteria/{id}/publish` | Publish a `DRAFT` criteria set; OCC-guarded by `expected_landlord_version`; closed-window overlap rejected | Landlord |
| POST | `/api/criteria/{id}/archive` | Archive a `DRAFT` or `PUBLISHED` criteria set; pinned applications keep evaluating against it | Landlord |
| POST | `/api/applicants` | Register an applicant (bureau intake) | Screener |
| POST | `/api/applications` | Create a screening application in `DRAFT`; landlord must be `ACTIVE` | Landlord |
| GET | `/api/applications` | List applications with optional filters; ownership-scoped for entity-backed callers | ComplianceAdmin, Screener, Landlord, Applicant |
| GET | `/api/applications/{id}` | Get one application | ComplianceAdmin, Screener, Landlord, Applicant |
| POST | `/api/applications/{id}/consent` | Applicant signs the screening consent; stamps `consent_signed_at` | Applicant |
| POST | `/api/applications/{id}/verify-identity` | Identity verification attempt; score of at least 70 verifies; at most 3 attempts; only in `DRAFT` or `SUBMITTED` | Screener |
| POST | `/api/applications/{id}/submit` | Submit a `DRAFT` application; pins the covering `PUBLISHED` criteria; portable applications get a re-swept copy and the flat fee | Landlord |
| POST | `/api/applications/{id}/record-searches` | Run the bureau record search; creates the report and records with the suppression sweep; charges the screening fee | Screener |
| POST | `/api/applications/{id}/withdraw` | Withdraw a non-terminal application; voids a DRAFT report and refunds the fee if never delivered | Landlord, Applicant |
| POST | `/api/applications/{id}/score` | Score a `SCREENING` application: snapshots income and record counts, computes affordability and the recommendation | Screener |
| POST | `/api/applications/{id}/decide` | Record the landlord's decision; `DENY` auto-creates a `DRAFT` adverse action notice with derived reason codes | Landlord |
| POST | `/api/applications/{id}/guarantors` | Add a guarantor/co-signer to a non-terminal application | Landlord |
| GET | `/api/guarantors` | List guarantors, optionally filtered by `application_id` | ComplianceAdmin, Screener, Landlord, Applicant |
| GET | `/api/guarantors/{id}` | Get one guarantor | ComplianceAdmin, Screener, Landlord, Applicant |
| POST | `/api/guarantors/{id}/evaluate` | Evaluate a guarantor under the pinned criteria's `guarantor_policy` | Screener |
| POST | `/api/applications/{id}/income-verifications` | Start income verification for a non-terminal application; at most one per application | Screener |
| GET | `/api/income-verifications` | List income verifications, optionally filtered by `application_id` | ComplianceAdmin, Screener, Landlord, Applicant |
| GET | `/api/income-verifications/{id}` | Get one income verification | ComplianceAdmin, Screener, Landlord, Applicant |
| POST | `/api/income-verifications/{id}/resolve` | Resolve a `PENDING` verification as `VERIFIED` or `FAILED` | Screener |
| POST | `/api/income-verifications/{id}/retry` | Re-open a `FAILED` verification to `PENDING`, clearing failure data | Screener |
| GET | `/api/reports` | List reports, optionally filtered by `application_id` or `source_report_id` | ComplianceAdmin, Screener, Landlord, Applicant |
| GET | `/api/reports/{id}` | Get one report | ComplianceAdmin, Screener, Landlord, Applicant |
| POST | `/api/reports/{id}/deliver` | Deliver a `DRAFT` report or re-deliver an `AMENDED` one; refreshes `last_delivered_at` | Screener |
| GET | `/api/records` | List screening records, optionally filtered by `report_id`; ordered by creation sequence | ComplianceAdmin, Screener, Landlord, Applicant |
| GET | `/api/records/{id}` | Get one screening record | ComplianceAdmin, Screener, Landlord, Applicant |
| POST | `/api/reports/{id}/disputes` | Applicant disputes report records; flips the report to `UNDER_DISPUTE` and the records to `DISPUTED` | Applicant |
| GET | `/api/disputes` | List disputes, optionally filtered by `report_id` or `applicant_id` | ComplianceAdmin, Screener, Landlord, Applicant |
| GET | `/api/disputes/{id}` | Get one dispute | ComplianceAdmin, Screener, Landlord, Applicant |
| POST | `/api/disputes/{id}/start-reinvestigation` | Open reinvestigation on a `FILED` dispute; reinvestigator must differ from the report's originator | Screener |
| POST | `/api/disputes/{id}/resolve` | Resolve a dispute (`UPHELD` restores and re-delivers; `CORRECTED` removes records, amends, and recomputes the recommendation) | Screener |
| GET | `/api/adverse-action-notices` | List adverse action notices, optionally filtered by `application_id` | ComplianceAdmin, Screener, Landlord, Applicant |
| GET | `/api/adverse-action-notices/{id}` | Get one adverse action notice | ComplianceAdmin, Screener, Landlord, Applicant |
| POST | `/api/adverse-action-notices/{id}/issue` | Issue a `DRAFT` notice; optional `reason_codes` override; every reason must be grounded in current data | Landlord |
| POST | `/api/adverse-action-notices/{id}/rescind` | Rescind an `ISSUED` notice | Landlord |
| POST | `/api/landlords/{id}/consistency-audits` | Run a consistency audit over the landlord's decided applications; creates an immutable ConsistencyAuditRun | ComplianceAdmin |
| GET | `/api/landlords/{id}/consistency-audits` | List a landlord's audit runs | ComplianceAdmin, Screener, Landlord, Applicant |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_OWNERSHIP_MISMATCH` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_NOT_REINVESTIGATOR` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_APPLICATION_TERMINAL` | 409 Conflict |
| `ERR_INVALID_APPLICATION_STATE` | 409 Conflict |
| `ERR_INVALID_CRITERIA_STATE` | 409 Conflict |
| `ERR_INVALID_REPORT_STATE` | 409 Conflict |
| `ERR_INVALID_DISPUTE_STATE` | 409 Conflict |
| `ERR_INVALID_INCOME_VERIFICATION_STATE` | 409 Conflict |
| `ERR_INVALID_GUARANTOR_STATE` | 409 Conflict |
| `ERR_INVALID_NOTICE_STATE` | 409 Conflict |
| `ERR_LANDLORD_SUSPENDED` | 409 Conflict |
| `ERR_INCOME_VERIFICATION_UNRESOLVED` | 409 Conflict |
| `ERR_RULE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_CRITERIA_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_INCOME_VERIFICATION_EXISTS` | 409 Conflict |
| `ERR_NO_PUBLISHED_CRITERIA` | 409 Conflict |
| `ERR_PORTABLE_SEARCH_FORBIDDEN` | 409 Conflict |
| `ERR_IDENTITY_ATTEMPTS_EXHAUSTED` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_CONSENT_REQUIRED` | 422 Unprocessable Entity |
| `ERR_IDENTITY_NOT_VERIFIED` | 422 Unprocessable Entity |
| `ERR_UNGROUNDED_ADVERSE_REASON` | 422 Unprocessable Entity |
| `ERR_DISPUTE_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_PORTABLE_REPORT_EXPIRED` | 422 Unprocessable Entity |
| `ERR_REINVESTIGATION_OVERDUE` | 422 Unprocessable Entity |
| `ERR_PORTABLE_REPORT_INVALID` | 422 Unprocessable Entity |
| `ERR_PORTABLE_REPORT_NOT_ACCEPTED` | 422 Unprocessable Entity |
| `ERR_RECORD_NOT_ON_REPORT` | 422 Unprocessable Entity |
