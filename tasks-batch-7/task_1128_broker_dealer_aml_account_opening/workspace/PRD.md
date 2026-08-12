# Broker-Dealer AML API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for the Broker-Dealer AML & Account Opening API, the compliance backbone for a broker-dealer's anti-money-laundering unit. The platform covers the full regulatory arc of a brokerage relationship: customer identification program (CIP) documentation at onboarding, beneficial ownership certification for legal-entity customers, quantitative risk rating with enhanced due diligence for high-risk accounts, securities-specific transaction monitoring (with particular attention to low-priced securities typologies), physical certificate deposit review, suspicious activity report (SAR) drafting and continuing-activity review, FinCEN 314(a) list scanning and response, and independent testing of the AML program itself.

The design is shaped by two regulatory realities. First, every decision must be attributable and auditable: the API enforces segregation of duties between the registered representatives who open relationships, the analysts who investigate them, the officers who approve or file, and the independent auditors who verify remediation. Second, compliance posture is never static. Document expirations, overdue reviews, confirmed list matches, and suspicious instruments continuously reshape an account's risk tier and its AML posture, and the system recomputes derived state after every trigger rather than waiting for human review. All resources are served under the `/aml` mount.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying a malformed value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. A request whose role is not permitted for the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE`.

Seven roles are recognized, spelled exactly as follows: `RegisteredRep`, `AMLAnalyst`, `ComplianceOfficer`, `SAROfficer`, `OperationsAnalyst`, `IndependentAuditor`, and `SystemAdmin`.

- A `RegisteredRep` is the registered representative who opens customers and accounts and submits CIP documents and beneficial ownership data. When `X-User-Role` is `RegisteredRep`, `X-User-ID` is the `id` of the acting RegisteredRep record; ownership checks on any resource that references a RegisteredRep compare the resource's foreign-key field to `X-User-ID`. In particular, a newly created customer's `registered_rep_id` is set from `X-User-ID` at creation.
- An `AMLAnalyst` verifies CIP documents, runs monitoring scans, triages alerts, opens and investigates cases, and conducts EDD reviews. When `X-User-Role` is `AMLAnalyst`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `recommending_analyst_id` on a case) but does not compare it to any entity's `id`.
- A `ComplianceOfficer` approves, declines, restricts, reinstates, and closes accounts; certifies beneficial ownership; completes EDD reviews; manages 314(a) responses; decides certificate deposits; and submits finding remediations. When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `reviewed_by` on a match or `submitted_by` on a finding) but does not compare it to any entity's `id`.
- A `SAROfficer` decides no-file outcomes, drafts and files SARs, and runs continuing reviews — organizationally segregated from the investigating analysts. When `X-User-Role` is `SAROfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity and is not compared to any entity's `id`.
- An `OperationsAnalyst` posts and reverses transactions and intakes, advances, supplements, and resubmits physical certificate deposits. When `X-User-Role` is `OperationsAnalyst`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity and is not compared to any entity's `id`.
- An `IndependentAuditor` plans and runs audit engagements, records findings, and verifies or accepts remediation — with no operational mutation rights elsewhere. When `X-User-Role` is `IndependentAuditor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `lead_auditor_id` on an engagement or `verified_by` on a finding) but does not compare it to any entity's `id`.
- A `SystemAdmin` manages reps, monitoring rules, the lost/stolen registry, the logical clock, and the daily sweep. When `X-User-Role` is `SystemAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity and is not compared to any entity's `id`.

All roles may use every read endpoint; write capabilities are partitioned per the endpoint table in §4.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items and defaults to 0. Values outside these bounds are rejected with `ERR_INVALID_REQUEST`.

Unless otherwise specified, all list endpoints return resources sorted by `created_at` in ascending order. The `meta` object of list responses carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every resource in this API — reps, customers, accounts, identification documents, certifications, owners, EDD reviews, transactions, monitoring rules, alerts, cases, SAR filings, 314(a) requests, matches, certificate deposits, lost/stolen registry entries, audit engagements, and findings — carries a uniform set of system-managed fields:

- `id` (string): a server-minted UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, stamped at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation.
- `version` (integer): starts at its initial value on creation and increments by one on every mutation of the resource, including system-driven transitions and cascade-driven updates.

Because every mutation increments `version` and refreshes `updated_at`, a client that observes a resource, then later submits a write against it, can detect intervening change purely by comparing versions (see §2.6).

### 2.5. The Logical Clock and the Daily Sweep

All time-based behavior in the system is governed by a logical clock, not wall-clock time. Before any administrative call sets it, the clock reads exactly `2026-05-01T00:00:00Z`; once set, it holds that value until the next set, and it never falls back to wall-clock time. A SystemAdmin moves the clock by supplying a `to_iso8601` instant; the capability responds with the resulting `current_utc` and performs no state recomputation of its own.

Time-based transitions are applied exclusively by an admin-only ops-run checkpoint, the daily sweep. Running the sweep at the current clock date applies six families of transitions:

1. **Document expiry**: any identification document in `VERIFIED` whose `expiry_date` is earlier than the clock date becomes `EXPIRED`, and the AML posture of every account belonging to that customer is recomputed.
2. **EDD refresh**: any EDD review in `APPROVED` whose `refresh_due_date` is earlier than the clock date becomes `REFRESH_DUE`, and the account's AML posture is recomputed.
3. **SAR continuing review**: any SAR filing still in `FILED` (not `SUPERSEDED`) whose `continuing_review_due_date` is earlier than the clock date has `review_overdue` set to true.
4. **314(a) overdue**: any request in `RECEIVED` or `SCAN_COMPLETE` whose `response_deadline` is earlier than the clock date becomes `OVERDUE`.
5. **Certificate hold release**: any deposit in `CLEARANCE_HOLD` whose `hold_release_date` is on or before the clock date becomes `READY_TO_ACCEPT` — release is inclusive, so a clock date equal to the release date releases the hold.
6. **Finding aging**: any finding in `OPEN` or `REMEDIATION_SUBMITTED` whose `remediation_deadline` is earlier than the clock date has `is_overdue` set to true and its severity escalated one level (see §3.9).

The sweep reports how many entities each family touched, via `documents_expired`, `edd_reviews_flagged`, `sar_reviews_due`, `requests_314a_overdue`, `holds_released`, and `findings_aged`. Every affected entity's `version` increments, and affected accounts recompute `aml_posture`. Boundaries throughout the API follow these same strict/inclusive rules: a date equal to a deadline is not overdue unless a specific rule states the comparison is inclusive.

### 2.6. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control, and each names its expected-version field explicitly:

- **Manual case opening** requires `expected_account_version`, carrying the client's last observed `version` of the target brokerage account. Opening a case legitimately mutates the account (case counts, risk recalculation, version bump), so if the account's current `version` no longer matches the submitted value, the create is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from acting on a stale view of the account.
- **Explicit risk recalculation** on an account likewise requires `expected_account_version`. Any account mutation since the client's observation — a posted transaction changing exposure, an alert creation, a case opening or closing, a posture change — invalidates the basis of the recalculation, so a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).
- **Certificate deposit decisions** require `expected_deposit_version`, the client's last observed `version` of the deposit. Because attaching a supplement legitimately advances the deposit's version while it sits decidable, a reviewer whose observation predates that bump is refused with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint accepts a version field; the remaining writes are serialized purely by their state preconditions.

### 2.7. Amounts, Percentages, and Rounding Discipline

All monetary amounts are represented at exactly 2 decimal places, rounded half up, and returned as numbers (not strings). Derived security-transaction amounts are computed per line: quantity multiplied by unit price, rounded half up to two decimal places, before any summation. Where several transactions are aggregated, each line amount is rounded half up to two decimal places first and the rounded values are then summed exactly — the system never sums raw products and rounds once at the end, because the two orders can differ by cents. Percentages (ownership shares) are compared at two decimal places. Risk scores and alert severities are integers; severity is rounded half up to a whole number. Calendar arithmetic (deadlines, holds, refresh dates) operates at day granularity on `YYYY-MM-DD` dates in UTC.

### 2.8. Resource Addressing and Existence Checks

Paths that carry multiple identifiers are validated left to right: the first path identifier that does not correspond to an existing resource determines the rejection, before any business rule is evaluated. Each resource type has its own not-found error: a missing rep yields `ERR_REP_NOT_FOUND`; a missing customer `ERR_CUSTOMER_NOT_FOUND`; a missing account `ERR_ACCOUNT_NOT_FOUND`; a missing document `ERR_DOCUMENT_NOT_FOUND`; a missing certification `ERR_CERTIFICATION_NOT_FOUND`; a missing owner `ERR_OWNER_NOT_FOUND`; a missing EDD review `ERR_EDD_REVIEW_NOT_FOUND`; a missing transaction `ERR_TRANSACTION_NOT_FOUND`; a missing monitoring rule `ERR_RULE_NOT_FOUND`; a missing alert `ERR_ALERT_NOT_FOUND`; a missing case `ERR_CASE_NOT_FOUND`; a missing SAR filing `ERR_SAR_FILING_NOT_FOUND`; a missing 314(a) request `ERR_FINCEN_REQUEST_NOT_FOUND`; a missing match `ERR_MATCH_NOT_FOUND`; a missing certificate deposit `ERR_DEPOSIT_NOT_FOUND`; a missing lost/stolen registry entry `ERR_LOST_STOLEN_ENTRY_NOT_FOUND`; a missing audit engagement `ERR_ENGAGEMENT_NOT_FOUND`; and a missing finding `ERR_FINDING_NOT_FOUND`. All not-found rejections carry HTTP 404.

### 2.9. Validation Precedence

When several checks could reject the same request, the server evaluates them in a fixed priority order, so the error a client observes is deterministic:

1. Header context first — a missing or malformed `X-User-ID` or `X-User-Role` surfaces as `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (400) before anything else.
2. Role authorization — an impermitted role for the endpoint yields `ERR_UNAUTHORIZED_ROLE` (403).
3. Segregation of duties — an identity-level SoD conflict yields `ERR_SOD_VIOLATION` (403); see §2.10.
4. Path existence — left-to-right 404 checks per §2.8.
5. Actor entity state — a suspended rep attempting to open customers, accounts, documents, or certifications is refused with `ERR_REP_SUSPENDED` (409) before the target resource's own state is examined.
6. Target lifecycle and actionability — the target resource must be in a state that permits the operation (account lifecycle for posting, actionable-state rules for reviews, alerts, cases, matches, deposits, findings, engagements, certifications, documents, transactions, filings, and requests), and OCC expected-version fields must match; violations surface as the appropriate state error from §5, or `ERR_STALE_VERSION` (412) for version mismatches.
7. Posture gate — a `SEVERE` account posture blocks all new transaction posting and certificate deposit intake with `ERR_POSTURE_SEVERE_BLOCKS` (403).
8. Lost/stolen registry — certificate numbers on the `ACTIVE` registry are refused with `ERR_CERT_REPORTED_LOST_STOLEN` (403), checked both at deposit intake and when advancing into authenticity review.
9. Approval gates — the four account-approval conditions of §3.3 (prohibited tier, CIP completeness, certified beneficial ownership, EDD approval for high-tier accounts) are enforced at approval time.
10. Reinstate blocks — unresolved confirmed matches and open critical cases refuse reinstatement with `ERR_MATCH_314A_UNRESOLVED` or `ERR_CRITICAL_CASE_OPEN` (409).
11. Uniqueness — duplicate `crd_number`, duplicate `request_reference`, and duplicate certificate numbers (against non-rejected deposits and the `ACTIVE` registry) are rejected with `ERR_DUPLICATE_CRD_NUMBER`, `ERR_DUPLICATE_314A_REQUEST`, or `ERR_DUPLICATE_CERTIFICATE_NUMBER` (409).
12. Temporal overlap — half-open EDD review periods and closed audit engagement windows reject overlaps with `ERR_OVERLAPPING_EDD_REVIEW` or `ERR_OVERLAPPING_AUDIT_ENGAGEMENT` (409).
13. Ownership aggregation — a certification whose owner percentages total more than 100.0 is rejected with `ERR_EXCESSIVE_OWNERSHIP_TOTAL` (422).
14. Date sanity — inverted or malformed date ranges yield `ERR_INVALID_DATE_RANGE` (400).
15. Cross-reference validity — wrong-type customers, non-draft certifications, mismatched origin alerts, invalid prior filings, and out-of-set enum values yield the referential errors of §3 (`ERR_CERTIFICATION_REQUIRES_LEGAL_ENTITY`, `ERR_CERTIFICATION_NOT_DRAFT`, `ERR_ALERT_ACCOUNT_MISMATCH`, `ERR_PRIOR_FILING_CASE_MISMATCH`, `ERR_INVALID_ENUM`, all 400).
16. Certification content — covered-owner KYC completeness, control-person presence, and coverage-or-attestation checks yield `ERR_OWNER_KYC_REQUIRED` or `ERR_CONTROL_PERSON_REQUIRED` (422).
17. Wire velocity — a projected thirty-day wire total strictly above the account's tier limit yields `ERR_VELOCITY_LIMIT_EXCEEDED` (422).
18. Rule availability — referencing a disabled monitoring rule yields `ERR_RULE_DISABLED` (409).
19. Close and filing blocks — case close with a draft filing, account close with open items, engagement close with open findings, an initial SAR draft against a case not recommended, and risk acceptance of a high-severity finding yield `ERR_CASE_HAS_OPEN_FILING`, `ERR_ACCOUNT_CLOSE_BLOCKED`, `ERR_ENGAGEMENT_HAS_OPEN_FINDINGS`, `ERR_CASE_NOT_SAR_RECOMMENDED`, or `ERR_RISK_ACCEPTANCE_NOT_ALLOWED` (409).
20. 314(a) completeness — a response submitted while any match remains unresolved yields `ERR_FINCEN_RESPONSE_INCOMPLETE` (409).
21. Request body shape — malformed bodies, missing required fields, and wrong types yield `ERR_INVALID_REQUEST` (400) only after every check above has passed.

### 2.10. Segregation of Duties

Beyond role-level partitioning, the API enforces two identity-level segregation rules. The SAR officer who files a SAR must not be the analyst who recommended it: filing compares `X-User-ID` to the case's `recommending_analyst_id`, and equality is rejected with `ERR_SOD_VIOLATION`. The auditor who verifies a finding's remediation must not be the officer who submitted it: verification compares `X-User-ID` to the finding's `submitted_by`, and equality is likewise rejected with `ERR_SOD_VIOLATION`. Both rejections carry HTTP 403 and apply regardless of seniority — no override exists.

### 2.11. Cascading Consistency Across the Book

Many operations mutate more than one resource, and every such cascade is atomic within the request: the primary mutation, every secondary transition, every recomputed aggregate, and every version increment all succeed or fail together. Restriction of an account fans out to its transactions, then to newly created alerts, then to a risk recalculation that reads the alert set the previous hop just produced — cascades compose in a defined hop order rather than running ad hoc. Compensating actions mirror this discipline: reversing a transaction restores the account's exposure and wire-velocity aggregates to their pre-post values, and a decide-no-file outcome returns the escalated alert and its transactions to their pre-escalation workload. Derived dimensions such as the account's AML posture are recomputed after every trigger and stored on the account row, so readers always see the current composite state rather than a snapshot.

## 3. Business Logic & Workflows

### 3.1. Reps, Customers, and CIP Document Verification

Everything begins with the registered-rep roster. A `SystemAdmin` onboards a rep by supplying `full_name` and `crd_number`; the CRD number must be unique across reps, and a duplicate is rejected with `ERR_DUPLICATE_CRD_NUMBER`. A rep starts `ACTIVE`. A `SystemAdmin` may later suspend the rep, moving `status` from `ACTIVE` to `SUSPENDED`, and reinstate, moving `SUSPENDED` back to `ACTIVE`; each change increments the rep's `version`, and attempting either transition from the wrong state is rejected with `ERR_INVALID_LIFECYCLE_TRANSITION`. Suspension is consequential downstream: a rep who is not `ACTIVE` cannot create customers, accounts, identification documents, or certifications — the attempt is refused with `ERR_REP_SUSPENDED` before any target-side validation runs.

A `RegisteredRep` opens a customer by providing `customer_type` (`INDIVIDUAL` or `LEGAL_ENTITY`), `full_name`, `tax_id`, and `country_risk_tier` (`LOW`, `MEDIUM`, `HIGH`, or `PROHIBITED`), with optional `is_pep` (defaulting to false) and `date_of_birth`. The customer's `registered_rep_id` is taken from `X-User-ID`, tying the book of business to the acting rep. The `date_of_birth` matters beyond record-keeping: for `INDIVIDUAL` customers it feeds identity matching elsewhere in the program, including 314(a) name-and-birthdate matching.

Customer listings can be filtered by `registered_rep_id`, `tax_id`, or `customer_type`; rep listings filter by `status`.

CIP evidence arrives as identification documents. A `RegisteredRep` submits a document against a customer with a `doc_type` of `GOVERNMENT_ID`, `FORMATION_DOC`, `PROOF_OF_ADDRESS`, or `W9`, plus `document_number` and `expiry_date`; the document enters `SUBMITTED`. An `AMLAnalyst` then dispositions it. Verification moves `SUBMITTED` → `VERIFIED` and is only defined from `SUBMITTED` — anything else draws `ERR_DOCUMENT_NOT_VERIFIABLE`. Verification carries two cascades: every other document of the same customer and same `doc_type` currently `VERIFIED` or `EXPIRED` becomes `SUPERSEDED`, and the AML posture of every account belonging to that customer is recomputed, because a fresh `VERIFIED` replacement can clear an expiry-driven elevation. Rejection moves `SUBMITTED` → `REJECTED` (any other state: `ERR_DOCUMENT_NOT_REJECTABLE`) and records the supplied `reason` in `rejection_reason`.

Documents also age. When the daily sweep finds a `VERIFIED` document whose `expiry_date` has passed relative to the clock date, the document moves `VERIFIED` → `EXPIRED`, and posture recomputation runs across the customer's accounts. A later `VERIFIED` replacement of the same type supersedes the expired one (`EXPIRED` → `SUPERSEDED`), again recomputing posture. `REJECTED` and `SUPERSEDED` are terminal. Document listings filter by `customer_id`, `status`, or `doc_type`.

### 3.2. Beneficial Ownership Certification for Legal Entities

Legal-entity customers must disclose their natural-person owners before an account can be approved. A `RegisteredRep` opens a BeneficialOwnershipCertification against the customer — but only when the customer's `customer_type` is `LEGAL_ENTITY`; otherwise the attempt is rejected with `ERR_CERTIFICATION_REQUIRES_LEGAL_ENTITY`. The rep may set `no_25pct_owner_attested` (default false) to attest that no natural person owns twenty-five percent or more. The certification starts `DRAFT`.

Owners are added one row at a time by a `RegisteredRep`, and only while the certification is `DRAFT` — adding to a certification in any other state yields `ERR_CERTIFICATION_NOT_DRAFT`. Each owner row carries `full_name`, `ownership_pct` (greater than zero and at most one hundred, expressed to two decimal places), and the flags `is_control_person` and `is_entity_owner` (both defaulting to false); `tax_id`, `date_of_birth`, and `address` are optional at entry time but become mandatory at certification time for any owner at or above the coverage threshold. Setting `is_entity_owner` to true marks a layered owner that is itself a legal entity, which feeds the ownership-opacity component of account risk scoring. Owner listings filter by `certification_id`.

Certification itself is performed by a `ComplianceOfficer` and runs the coverage battery. The certification must be `DRAFT` (else `ERR_CERTIFICATION_NOT_DRAFT`). The `total_ownership_pct` — the sum of `ownership_pct` across all owner rows — must not exceed 100.0, or the attempt is rejected with `ERR_EXCESSIVE_OWNERSHIP_TOTAL`. At least one owner must have `is_control_person` set, else `ERR_CONTROL_PERSON_REQUIRED`. Every covered owner — one whose `ownership_pct` is at least 25.00, with exactly 25.00 counting as covered — must present `tax_id`, `date_of_birth`, and `address` in full, else `ERR_OWNER_KYC_REQUIRED`. Finally, either at least one covered owner must exist or `no_25pct_owner_attested` must be true; failing both draws `ERR_OWNER_KYC_REQUIRED` as well.

On successful certification the record moves `DRAFT` → `CERTIFIED`, `certified_at` is stamped, and two computed fields are fixed: `total_ownership_pct` as the summed percentages and `covered_owner_count` as the number of covered owners whose full KYC triplet is present. Any previously `CERTIFIED` certification for the same customer becomes `SUPERSEDED` in the same action; `SUPERSEDED` is terminal. Certification listings filter by `customer_id` or `status`.

### 3.3. Account Opening and Risk Scoring

A `RegisteredRep` opens a brokerage account by naming the `customer_id` and a `product_set` drawn from the product types `CASH`, `LOW_PRICED_SECURITIES`, `MARGIN`, `OPTIONS`, and `CORRESPONDENT`. The account enters `PENDING_APPROVAL` with `aml_posture` set to `STANDARD`, and the system immediately computes the account's initial risk profile.

The **risk score** is an integer clamped between 0 and 100, assembled from weighted components. Country contributes 0 points for `LOW`, 10 for `MEDIUM`, or 25 for `HIGH`; a customer whose `country_risk_tier` is `PROHIBITED` is assigned risk tier `PROHIBITED` outright, regardless of any score arithmetic. Customer type adds 10 points for `LEGAL_ENTITY` and nothing for `INDIVIDUAL`. A politically exposed customer (`is_pep`) adds 20 points. Products add 15 points when `LOW_PRICED_SECURITIES` is present in `product_set`, 5 each for the `MARGIN` and `OPTIONS` products, and 10 for `CORRESPONDENT`, with the product contribution capped at 25 points in total. Ownership opacity adds 10 points when a `LEGAL_ENTITY` customer's currently `CERTIFIED` certification contains any owner with `is_entity_owner` true. These static components are the whole story at creation: the `INITIAL` variant of the score adds no activity component at all, and approval re-stamps this same `INITIAL` computation, recording `risk_variant_used` as `INITIAL`.

The **ONGOING** variant, used by explicit recalculation, alert escalation, case opening, and 314(a) confirmation, adds an activity component on top of the identical static profile — so the same profile scores higher once activity exists. Activity contributes 5 points per monitoring alert of the account currently in `UNDER_REVIEW` or `ESCALATED_TO_CASE`, plus 10 points per `FILED` SAR filing belonging to cases of the account, plus a velocity-band component. The velocity band compares the account's `wire_velocity_30d_amount` to a tier limit — 250000 for `LOW`, 100000 for `MEDIUM`, 25000 for `HIGH`, evaluated against the tier in effect before this recalculation (at creation, the `LOW` limit is used). A ratio below one half contributes nothing; a ratio of at least one half but less than four fifths contributes 5 points; a ratio of at least four fifths contributes 10 points. The resulting score maps to tiers inclusively at the lower bound: a score of at least 70 yields `HIGH`, at least 40 (but below 70) yields `MEDIUM`, and anything lower yields `LOW` — with the `PROHIBITED` override standing above all scoring.

An explicit recalculation by an `AMLAnalyst` or `ComplianceOfficer` runs the `ONGOING` variant, stamps `risk_variant_used` as `ONGOING`, recomputes `aml_posture`, and increments the account's `version`; it is one of the three OCC-guarded writes of §2.6 and must carry `expected_account_version`.

Account listings filter by `customer_id`, `lifecycle_status`, `risk_tier`, or `aml_posture`.

Approval is the pivotal decision and belongs to a `ComplianceOfficer`. Four gates must all pass. First, CIP must be complete: an `INDIVIDUAL` customer needs at least one `VERIFIED` document of type `GOVERNMENT_ID`, while a `LEGAL_ENTITY` customer needs `VERIFIED` documents of both `FORMATION_DOC` and `PROOF_OF_ADDRESS` types — shortfalls are rejected with `ERR_CIP_INCOMPLETE`. Second, a `LEGAL_ENTITY` customer must have a certification in `CERTIFIED` status, else `ERR_BENEFICIAL_OWNERSHIP_REQUIRED`. Third, a `PROHIBITED` risk tier can never be approved, under any circumstance: `ERR_PROHIBITED_TIER`. Fourth, a `HIGH`-tier account requires an `APPROVED` EDD review for the account before approval, else `ERR_EDD_APPROVAL_REQUIRED`. Successful approval moves `PENDING_APPROVAL` → `OPEN`, recomputes `aml_posture` (which settles to `STANDARD` absent elevation triggers), re-stamps the `INITIAL` risk variant, and increments the account's `version`. Alternatively, a `ComplianceOfficer` may decline the application, moving `PENDING_APPROVAL` → `DECLINED` and recording the supplied `reason` in `decline_reason`; declining from any state other than `PENDING_APPROVAL` is rejected with `ERR_INVALID_LIFECYCLE_TRANSITION`.

An `OPEN` account can be restricted by a `ComplianceOfficer` (who may supply a `reason`), moving `OPEN` → `RESTRICTED`; restriction also arrives system-side from a confirmed 314(a) match or a rejected EDD review. Restriction cascades in a fixed order: every transaction of the account currently `POSTED` becomes `FLAGGED`; for each newly flagged transaction lacking any alert in `NEW`, `UNDER_REVIEW`, or `ESCALATED_TO_CASE`, a new `MonitoringAlert` is created in `NEW` with a `rule_code` reflecting the cause; and the account's risk is then recalculated with the `ONGOING` variant, reading the alert set the previous hop just produced. Attempting restriction from anything but `OPEN` draws `ERR_INVALID_LIFECYCLE_TRANSITION`.

Reinstatement returns a `RESTRICTED` account to `OPEN`, but only while no 314(a) match for the account remains in `CONFIRMED` (`ERR_MATCH_314A_UNRESOLVED`) and no case of `CRITICAL` priority sits in `OPEN`, `INVESTIGATING`, `SAR_RECOMMENDED`, or `REOPENED` (`ERR_CRITICAL_CASE_OPEN`).

Closure, from either `OPEN` or `RESTRICTED`, is barred while any of four classes of open items exist: a case in `OPEN`, `INVESTIGATING`, `SAR_RECOMMENDED`, `REOPENED`, `DECIDED_FILED`, or `DECIDED_NO_FILE`; a match in `PENDING_REVIEW` or `CONFIRMED`; a certificate deposit in any state other than `ACCEPTED`, `REJECTED`, or `REJECTED_SUSPICIOUS`; or a transaction in `FLAGGED` or `ESCALATED`. Each of these blocks surfaces as `ERR_ACCOUNT_CLOSE_BLOCKED`. `CLOSED` and `DECLINED` are terminal — any further lifecycle transition from them is rejected with `ERR_ACCOUNT_CLOSED_TERMINAL`.

### 3.4. The AML Posture Dimension and Enhanced Due Diligence

Parallel to its lifecycle, every account carries a second, system-managed dimension: `aml_posture`, with values `STANDARD`, `ELEVATED`, and `SEVERE`. Clients never set posture directly; the server recomputes it after every posture trigger and stores the result on the account row, incrementing `version` whenever the stored value changes. Posture gates money movement: `SEVERE` blocks all new transaction posting and all certificate deposit intake with `ERR_POSTURE_SEVERE_BLOCKS`, while `ELEVATED` automatically flags every newly posted transaction.

Elevation from `STANDARD` to `ELEVATED` occurs when any of four triggers is present: a `VERIFIED` identification document on the customer has expired and not yet been superseded; an EDD review of the account sits in `REFRESH_DUE`; the account's `has_suspicion_flag` is set; or the account's `risk_score` is at least 70. Posture rises to `SEVERE` — directly from either `STANDARD` or `ELEVATED` — when a match for the account exists in `CONFIRMED`, or when a case of `CRITICAL` priority exists in `OPEN`, `INVESTIGATING`, `SAR_RECOMMENDED`, or `REOPENED`. Demotion mirrors escalation: once all `CONFIRMED` matches are `RESOLVED` and all `CRITICAL` cases have been decided or closed, posture falls from `SEVERE` to `ELEVATED` if an elevation trigger remains, or all the way to `STANDARD` if none does. An `ELEVATED` posture driven purely by an expired document relaxes to `STANDARD` once the expired document is `SUPERSEDED` by a newly `VERIFIED` replacement and no other elevation trigger exists. The `has_suspicion_flag`, once set by a suspicious-certificate decision, is never automatically cleared, so it pins posture at `ELEVATED` or above indefinitely.

**Enhanced due diligence** is the recurring review discipline for elevated-risk accounts. An `AMLAnalyst` opens an EDD review with `period_start` (inclusive), `period_end` (exclusive), and `trigger_reason`, optionally linking `prior_review_id` to the review being refreshed. The period is half-open: it includes its start date and excludes its end date, `period_end` must be later than `period_start` (`ERR_INVALID_DATE_RANGE` otherwise), and the half-open period must not overlap any existing non-`REJECTED` review for the same account (`ERR_OVERLAPPING_EDD_REVIEW`). Reviews enter `PENDING`.

An `AMLAnalyst` begins a review, moving `PENDING` → `IN_REVIEW` — and the same begin action also serves a review in `REFRESH_DUE`, moving `REFRESH_DUE` → `IN_REVIEW`; beginning from any other state is rejected with `ERR_EDD_REVIEW_NOT_ACTIONABLE`. Completion belongs to a `ComplianceOfficer`, who supplies a `decision` and optional `notes` (recorded in `decision_notes`); completion is only defined from `IN_REVIEW` (`ERR_EDD_REVIEW_NOT_ACTIONABLE` otherwise).

A completion with decision `APPROVED` captures `tier_at_completion` from the account's current `risk_tier` — immutable thereafter — and schedules `refresh_due_date` as the completion date plus an interval fixed by that captured tier: twelve calendar months for `HIGH`, twenty-four for `MEDIUM`, thirty-six for `LOW`, preserving the day of month. The account's posture is then recomputed. When the daily sweep later finds an `APPROVED` review whose `refresh_due_date` is strictly earlier than the clock date, the review flips to `REFRESH_DUE` — a date equal to the clock date is not yet due — and posture recomputes again, since a `REFRESH_DUE` review is itself an elevation trigger.

A completion with decision `REJECTED` cascades to the account: if the account is still `PENDING_APPROVAL` it moves to `DECLINED` with the EDD rejection recorded in `decline_reason`; if it is `OPEN` it moves to `RESTRICTED` with the full restriction cascade of §3.3 (posted transactions flagged, alerts created, `ONGOING` risk recalculated). Review listings filter by `account_id`, `status`, or `prior_review_id`.

### 3.5. Transactions, Monitoring Rules, and Alert Triage

With an account `OPEN`, a `RegisteredRep` or `OperationsAnalyst` posts transactions. Posting against an account in `RESTRICTED` is refused with `ERR_ACCOUNT_RESTRICTED`; against a `CLOSED` or `DECLINED` account with `ERR_ACCOUNT_CLOSED_TERMINAL`; and against an account in any other non-`OPEN` state with `ERR_ACCOUNT_NOT_OPEN`. A `SEVERE` posture independently blocks posting with `ERR_POSTURE_SEVERE_BLOCKS`, while an `ELEVATED` posture lets the post through but flags it immediately.

Each transaction carries a `txn_type` of `DEPOSIT_CERT`, `DEPOSIT_DTC`, `BUY`, `SELL`, `WIRE_OUT`, or `JOURNAL`. Security-type movements (`DEPOSIT_CERT`, `DEPOSIT_DTC`, `BUY`, `SELL`) take a `security_id` and require `quantity` and `unit_price`; their `amount` is computed as quantity times unit price, rounded half up to two decimal places, and any client-sent `amount` is ignored. For `WIRE_OUT` and `JOURNAL`, `amount` is supplied directly. A transaction's `is_low_priced` flag is true exactly when the transaction is a security type and its `unit_price` is below 5.00 — a price of exactly 5.00 is not low-priced — and is always false for `WIRE_OUT` and `JOURNAL`. New transactions normally land in `POSTED`; against an `ELEVATED` account they land directly in `FLAGGED`.

Wire discipline applies at posting. The account's `wire_velocity_30d_amount` is the sum of `amount` over its `WIRE_OUT` transactions not in `REVERSED` whose dates fall in the trailing thirty calendar days, both ends inclusive. Posting a new wire is checked by projection: the new wire's amount is added to the current total, and only a projected total strictly greater than the tier limit in effect at posting time (250000 for `LOW`, 100000 for `MEDIUM`, 25000 for `HIGH`) is rejected with `ERR_VELOCITY_LIMIT_EXCEEDED` — a projection exactly equal to the limit passes.

Two aggregates track every account's rolling activity and are recomputed on every post and every reversal. The `exposure_30d_amount` sums `amount` over all of the account's transactions not in `REVERSED` within the trailing thirty calendar days inclusive, and the `exposure_tier` buckets it: `T1` below 100000, `T2` from 100000 up to but excluding 500000, and `T3` at 500000 or more — exactly 500000 is `T3`. The `wire_velocity_30d_amount` is the same window restricted to wires. Posting also increments the account's `version`.

An `AMLAnalyst` clears a flagged transaction, moving `FLAGGED` → `CLEARED` (any other state: `ERR_TRANSACTION_NOT_CLEARABLE`); cleared transactions continue to count toward exposure and velocity. An `OperationsAnalyst` reverses a transaction from `POSTED` or `FLAGGED` (otherwise `ERR_TRANSACTION_NOT_REVERSIBLE`), recording the supplied `reason` in `reversal_reason`. Reversal is a compensating action: exposure and wire velocity are recomputed excluding the reversed transaction, so that posting followed by reversal leaves both aggregates equal to their pre-post values, and both the transaction's and the account's `version` increment. Transactions also move without client action: a scan match, an elevated posture at post time, or an account restriction moves `POSTED` → `FLAGGED`; escalation of the owning alert moves `FLAGGED` → `ESCALATED`; and a case decided no-file moves linked `ESCALATED` transactions to `CLEARED`. Transaction listings filter by `account_id`, `status`, or `txn_type`.

**Monitoring rules** codify the typologies the desk watches. A `SystemAdmin` creates a rule with a `rule_code` of `LPS_LIQUIDATION`, `LPS_DEPOSIT_LIQUIDATE`, `WIRE_VELOCITY`, or `STRUCTURING`, a `threshold_amount`, and a `window_days` length describing a trailing calendar-day window inclusive at both ends. `min_transaction_count` defaults to 1 (a structuring rule typically uses 3), and `enabled` defaults to true. Rules may later be adjusted — `enabled`, `threshold_amount`, `window_days`, or `min_transaction_count` — each update incrementing the rule's `version`. Disabled rules are skipped by scans, and any direct reference to a disabled rule is rejected with `ERR_RULE_DISABLED`. Rule listings filter by `rule_code` or `enabled`.

An `AMLAnalyst` runs a monitoring scan as an ops action: the scan evaluates every enabled rule against each account's trailing window and creates deduplicated alerts. A rule fires when its aggregate over matching transactions reaches or exceeds its `threshold_amount` and the number of matching transactions is at least `min_transaction_count`. For the `LPS_LIQUIDATION` rule the matching set is the account's `SELL` transactions with `is_low_priced` true, in `POSTED`, `FLAGGED`, or `ESCALATED`, dated within the window; each matching line's proceeds are computed as quantity times unit price rounded half up to two decimal places, and the alert's `aggregate_amount` is the exact sum of those rounded line amounts — the round-per-line-then-sum order is pinned, since the alternative (summing raw products and rounding once) can differ by cents. Deduplication suppresses a new alert when one with the same rule code, same account, and same window end already exists in `NEW`, `UNDER_REVIEW`, or `ESCALATED_TO_CASE`. Matched `POSTED` transactions become `FLAGGED`, and the run reports `alerts_created` and `transactions_flagged`.

Each alert records `rule_id` and a denormalized `rule_code` (cascade-created alerts may instead carry `FINCEN_314A_MATCH` or `CERT_SUSPICION`), the `account_id`, the `transaction_id` of the triggering transaction — the one with the greatest `created_at`, breaking ties by greatest amount and then by smallest quantity — and the inclusive `window_start` and `window_end` dates used by the scan, where `window_end` is the clock date at scan time and doubles as a dedup component. The alert's `severity` is frozen at creation: it is one hundred times the lesser of the aggregate-to-threshold ratio and 2.0, multiplied by a risk multiplier of 1.0 plus one quarter when the account's `risk_tier` is `HIGH` and plus one tenth when it is `MEDIUM`, and the result rounded half up to a whole number. Because severity is frozen, later risk changes do not rewrite existing alerts — they only shift the multiplier a future alert would get.

Alert triage belongs to an `AMLAnalyst`. Beginning review moves `NEW` → `UNDER_REVIEW`; an alert in any other state is not actionable and yields `ERR_ALERT_NOT_ACTIONABLE`. Closing with no action moves `UNDER_REVIEW` → `CLOSED_NO_ACTION` and records the supplied `rationale` in `close_rationale`. Reopening moves `CLOSED_NO_ACTION` → `UNDER_REVIEW` (again, only from `CLOSED_NO_ACTION`, else `ERR_ALERT_NOT_ACTIONABLE`). Every one of these transitions recomputes the account's `open_alert_count` — the number of its alerts in `NEW` or `UNDER_REVIEW`. Alert listings filter by `account_id`, `transaction_id`, `rule_id`, or `status`.

Escalation is the consequential step: an `AMLAnalyst` escalates an alert from `UNDER_REVIEW` to `ESCALATED_TO_CASE`, which creates an `AMLCase` and returns the new `alert_id`, `case_id`, and `case_priority`. Escalation follows a pinned evaluation order that resolves what would otherwise look circular: first the alert moves and the case is created in `OPEN` with `origin_alert_id` pointing back; second, the case's `priority` is assigned from the alert's severity exactly as frozen at alert creation — at least 150 yields `CRITICAL`, at least 100 yields `HIGH`, at least 50 yields `MEDIUM`, anything lower yields `LOW` — before any recalculation runs; third, the account's risk is recalculated with the `ONGOING` variant; and fourth, `open_alert_count` and `open_case_count` are recomputed. The triggering transaction, if `FLAGGED`, becomes `ESCALATED`, and both the alert's and the account's `version` increment.

### 3.6. Case Investigation and SAR Filing

Cases arise two ways: by escalation, as just described, or manually. An `AMLAnalyst` opens a manual case against an account, optionally naming an `origin_alert_id` — which must belong to the same account, else `ERR_ALERT_ACCOUNT_MISMATCH`. Manual opening is OCC-guarded per §2.6 and must carry `expected_account_version`. A manual case starts in `OPEN` with `priority` defaulted to `MEDIUM` (an alert-derived case instead takes the priority mapped from the alert's frozen severity), and opening recomputes the account's risk with the `ONGOING` variant, recomputes `open_case_count` — cases in `OPEN`, `INVESTIGATING`, `SAR_RECOMMENDED`, or `REOPENED` — and increments the account's `version`. Case listings filter by `account_id`, `origin_alert_id`, `status`, or `priority`.

Investigation begins when an `AMLAnalyst` moves the case from `OPEN` (or, after a reopen, from `REOPENED`) to `INVESTIGATING`; any other state draws `ERR_CASE_NOT_ACTIONABLE`. When the evidence supports reporting, the analyst recommends a SAR, moving `INVESTIGATING` → `SAR_RECOMMENDED` and supplying `recommendation_note` and `initial_detection_date`; the system stamps `recommending_analyst_id` from `X-User-ID`, and the recorded `initial_detection_date` anchors the initial filing deadline. Recommending from any state other than `INVESTIGATING` is rejected with `ERR_CASE_NOT_ACTIONABLE`.

A `SAROfficer` may instead decide not to file, from either `INVESTIGATING` or `SAR_RECOMMENDED`, moving the case to `DECIDED_NO_FILE` with a `rationale`. The decision compensates the escalation that brought the case in: the origin alert (if any) returns from `ESCALATED_TO_CASE` to `UNDER_REVIEW`, linked `ESCALATED` transactions become `CLEARED`, the account's open counts and posture are recomputed, and both the case's and the account's `version` increment — leaving the account's open workload as it was before the escalate and decide-no-file pair. Closing a case is allowed from `DECIDED_NO_FILE` or `DECIDED_FILED`, but not while any SAR filing for the case remains in `DRAFT` (`ERR_CASE_HAS_OPEN_FILING`); closing recomputes `open_case_count` and posture. Finally, an `AMLAnalyst` may reopen a `CLOSED` case with a `reason`, recorded in `reopen_reason`, moving `CLOSED` → `REOPENED` and recomputing counts and posture — closure is therefore never a one-way door, and no case state is absorbing.

**SAR drafting and filing** sit with the `SAROfficer`. A draft is created with `case_id`, `narrative`, `activity_start`, and `activity_end` (which must not precede the start, else `ERR_INVALID_DATE_RANGE`), entering `DRAFT`. Two variants exist. An *initial* filing — one with no `prior_filing_id` — requires its case to be in `SAR_RECOMMENDED`, else `ERR_CASE_NOT_SAR_RECOMMENDED`, and its `filing_deadline` is the case's `initial_detection_date` plus thirty calendar days. A *continuing-activity* filing sets `prior_filing_id` to a filing of the same case currently in `FILED` status, with the case itself in `DECIDED_FILED`; a prior filing from another case, or one not `FILED`, is rejected with `ERR_PRIOR_FILING_CASE_MISMATCH`. The continuing variant's `filing_deadline` is the prior filing's `filed_at` date plus one hundred twenty calendar days — a different, later anchor than an initial filing for the same detection date. Filing listings filter by `case_id`, `prior_filing_id`, or `status`.

Filing a draft — only possible from `DRAFT`, else `ERR_SAR_NOT_FILABLE` — is subject to the segregation rule of §2.10: the filer's `X-User-ID` must differ from the case's `recommending_analyst_id`, on pain of `ERR_SOD_VIOLATION`. Filing stamps `filed_at`, computes `filed_late` (true exactly when the filed date is later than the `filing_deadline`), and sets `continuing_review_due_date` to the filed date plus ninety calendar days. For an initial filing, the case moves `SAR_RECOMMENDED` → `DECIDED_FILED` in the same action; for a continuing filing, the prior filing moves `FILED` → `SUPERSEDED`.

Continuing review keeps filed SARs under the discipline. A `SAROfficer` records a continuing review against a `FILED` filing with an `outcome` and a `note`, optionally refreshing `narrative`, `activity_start`, and `activity_end`. Each review increments `continuing_review_count`, stamps `last_continuing_review_at`, clears `review_overdue`, and returns `new_draft_filing_id` and `next_review_due`. When the outcome is `CONTINUING_ACTIVITY`, a new `DRAFT` filing is created in the same action with its `prior_filing_id` set to the reviewed filing and a deadline one hundred twenty days after that filing's filed date. Meanwhile the daily sweep watches the calendar: a filing still `FILED` whose `continuing_review_due_date` has passed gets `review_overdue` set true.

### 3.7. FinCEN 314(a) List Processing

When FinCEN issues a 314(a) list, a `ComplianceOfficer` registers the request with its `request_reference` — unique across requests, with duplicates rejected as `ERR_DUPLICATE_314A_REQUEST` — and the `subjects` array, each subject carrying a `name`, an optional `tax_id`, an optional `date_of_birth`, and a `subject_type` of `INDIVIDUAL` or `ENTITY`. Registration stamps `received_at` from the logical clock, computes `response_deadline` as the received date plus fourteen calendar days, and places the request in `RECEIVED`. Request listings filter by `status`.

Scanning, also a `ComplianceOfficer` action, is defined only from `RECEIVED` (otherwise `ERR_FINCEN_REQUEST_NOT_SCANNABLE`) and moves the request to `SCAN_COMPLETE`. Matching is deterministic. A subject matches a customer account on `TAX_ID_EXACT` when the subject's `tax_id` equals the customer's `tax_id`; failing that, on `NAME_DOB` when the subject is an `INDIVIDUAL` and both a case-insensitive name match and an equal `date_of_birth` hold; failing that, on `NAME_EXACT` when the names match case-insensitively. One `Match314A` row is generated per subject-and-account pair, recording `request_id`, `account_id`, the `matched_subject_name`, and the strongest applicable `match_basis`, and the request's `match_count` is recomputed. Matches enter `PENDING_REVIEW` and can be listed filtered by `request_id`, `account_id`, or `status`.

Match disposition belongs to the `ComplianceOfficer`, and all three dispositions require `PENDING_REVIEW` (or, for resolution, `CONFIRMED`) — anything else yields `ERR_MATCH_NOT_REVIEWABLE`. Marking a false positive moves `PENDING_REVIEW` → `FALSE_POSITIVE` with a `rationale` and stamps `reviewed_by` from `X-User-ID`. Resolution moves `CONFIRMED` → `RESOLVED` and recomputes posture, which may relax from `SEVERE` once no `CONFIRMED` matches remain.

Confirmation is the heavyweight: `PENDING_REVIEW` → `CONFIRMED` stamps `reviewed_by` and fires a four-hop cascade. Hop one restricts the account (moving it `OPEN` → `RESTRICTED` when it is `OPEN`) and drives `aml_posture` to `SEVERE`. Hop two, caused by the restriction, flags every `POSTED` transaction of the account. Hop three, caused by the flagging, creates a `NEW` alert with `rule_code` `FINCEN_314A_MATCH` for each newly flagged transaction that lacks an open alert. Hop four, caused by the alert creation, recalculates the account's risk with the `ONGOING` variant, reading the alert set hop three produced. Both the match's and the account's `version` increment.

Response submission closes the loop: from `SCAN_COMPLETE` — or from `OVERDUE`, since the daily sweep flips a request whose `response_deadline` has passed from `RECEIVED` or `SCAN_COMPLETE` into `OVERDUE` — a `ComplianceOfficer` submits the response, but only once every match of the request sits in `FALSE_POSITIVE` or `RESOLVED`; otherwise `ERR_FINCEN_RESPONSE_INCOMPLETE`. Submission stamps `responded_at`, computes `responded_late` as true exactly when the responded date is later than the `response_deadline`, and lands the request in its terminal `RESPONSE_SUBMITTED` state. A request in a state that permits neither scanning nor response draws `ERR_FINCEN_REQUEST_NOT_SCANNABLE`.

### 3.8. Physical Certificate Deposits and the Lost/Stolen Registry

Physical certificates arrive over the counter and carry their own review pipeline. A `SystemAdmin` maintains the lost/stolen registry by reporting a `certificate_number` and `cusip`; registry numbers are unique (`ERR_DUPLICATE_CERTIFICATE_NUMBER`), and entries live in `ACTIVE` (or, once withdrawn from circulation concerns, `CANCELLED`). Registry listings filter by `certificate_number` or `status`.

Intake is performed by an `OperationsAnalyst` against an `OPEN` account — the same lifecycle refusals as transaction posting apply, and a `SEVERE` posture blocks intake outright with `ERR_POSTURE_SEVERE_BLOCKS`. The analyst records `certificate_number`, `cusip`, `security_name`, `quantity` (a positive whole number of shares), `unit_price` as the estimated price at intake, and optionally `has_restrictive_legend` (default false). Two safety checks fire at intake: the certificate number must not appear on an `ACTIVE` lost/stolen entry, else `ERR_CERT_REPORTED_LOST_STOLEN`; and the number must be unique among deposits not in `REJECTED` or `REJECTED_SUSPICIOUS`, else `ERR_DUPLICATE_CERTIFICATE_NUMBER`. Intake creates the deposit in `RECEIVED`, computes `is_low_priced` (true exactly when `unit_price` is below 5.00), and — in the same action — books the linked `DEPOSIT_CERT` security transaction directly in `FLAGGED` status, with exposure recomputed on the account. Deposit listings filter by `account_id`, `transaction_id`, or `status`.

Review advances one step at a time under an `OperationsAnalyst`. From `RECEIVED` the deposit moves to `ELIGIBILITY_REVIEW`; from there to `AUTHENTICITY_REVIEW`; from there to `CLEARANCE_HOLD`; each advance is defined only from its named state, and anything else is rejected with `ERR_DEPOSIT_NOT_ADVANCEABLE`. The lost/stolen check fires a second time at the door of authenticity review: advancing into `AUTHENTICITY_REVIEW` is refused with `ERR_CERT_REPORTED_LOST_STOLEN` if an `ACTIVE` registry entry for the certificate number has appeared since intake. Entering `CLEARANCE_HOLD` stamps `hold_release_date`: the hold lasts ten calendar days for a low-priced certificate and five otherwise, plus five additional days when `has_restrictive_legend` is set — so a low-priced certificate with a restrictive legend waits fifteen days. The daily sweep releases a hold whose `hold_release_date` is on or before the clock date, moving `CLEARANCE_HOLD` → `READY_TO_ACCEPT`. While a deposit sits in review, the analyst may attach a `note` via the supplement capability, which changes no state but does increment the deposit's `version` — precisely the interleaving the decision's OCC guard of §2.6 protects against.

Deciding a deposit belongs to a `ComplianceOfficer` and is possible only from `READY_TO_ACCEPT` (`ERR_DEPOSIT_NOT_DECIDABLE` otherwise). The decision request carries `expected_deposit_version` (see §2.6), an `outcome`, and an optional `reason` recorded in `decision_reason`. Three outcomes exist. **Accept** moves `READY_TO_ACCEPT` → `ACCEPTED` and clears the linked deposit transaction from `FLAGGED` to `CLEARED`. **Reject** moves to `REJECTED` and reverses the linked transaction (`FLAGGED` → `REVERSED`), recomputing exposure and velocity without it. **Reject-suspicious** moves to the terminal `REJECTED_SUSPICIOUS` and fires a three-hop cascade: hop one reverses the linked transaction; hop two, caused by the reversal, sets the account's `has_suspicion_flag` to true and recomputes posture — which lands at `ELEVATED` at minimum, and the flag never auto-clears; hop three, caused by the suspicion flag, creates a `NEW` alert with `rule_code` `CERT_SUSPICION` whose `transaction_id` is the reversed transaction. A rejected deposit may cycle back: an `OperationsAnalyst` resubmits it with a `note`, moving `REJECTED` → `RESUBMITTED` (`ERR_DEPOSIT_NOT_RESUBMITTABLE` from any other state), and a subsequent advance from `RESUBMITTED` skips eligibility and enters `AUTHENTICITY_REVIEW` directly — with the lost/stolen re-check still applied at that door.

### 3.9. Independent Testing and Audit

The program's fourth line of defense is the independent audit function. An `IndependentAuditor` plans an engagement with a `scope_unit` of `AML_PROGRAM`, `CIP_PROCESS`, `SANCTIONS_SCREENING`, or `TRANSACTION_MONITORING`, plus `start_date` and `end_date` describing a closed interval — both dates inclusive, with `end_date` not earlier than `start_date` (`ERR_INVALID_DATE_RANGE` otherwise). Engagement windows must not overlap any other non-`CLOSED` engagement of the same `scope_unit` (`ERR_OVERLAPPING_AUDIT_ENGAGEMENT`). The engagement enters `PLANNED` with `lead_auditor_id` stamped from `X-User-ID`. Engagement listings filter by `status` or `scope_unit`.

Fieldwork begins on the auditor's action, `PLANNED` → `FIELDWORK`, and reporting moves `FIELDWORK` → `REPORTED` with a `report_summary`; both transitions require the named source state, else `ERR_ENGAGEMENT_NOT_ACTIVE`. Findings are recorded while the engagement is in `FIELDWORK` or `REPORTED` — recording against an engagement in any other state is refused with `ERR_ENGAGEMENT_NOT_ACTIVE` — each with a `severity` of `CRITICAL`, `HIGH`, `MEDIUM`, or `LOW` and a `description`, entering `OPEN`. A finding's `remediation_deadline` is fixed at issuance from its initial severity: thirty days for `CRITICAL`, sixty for `HIGH`, ninety for `MEDIUM`, one hundred eighty for `LOW`, counted in calendar days from the created date, and the deadline never moves afterwards. The daily sweep ages findings: an `OPEN` or `REMEDIATION_SUBMITTED` finding whose deadline is strictly earlier than the clock date has `is_overdue` set true and its severity escalated one level — `LOW` to `MEDIUM`, `MEDIUM` to `HIGH`, `HIGH` to `CRITICAL`, with `CRITICAL` unchanged — while a deadline equal to the clock date is not yet overdue. Finding listings filter by `engagement_id`, `status`, or `severity`.

Remediation is a two-party handshake. A `ComplianceOfficer` submits remediation on an `OPEN` finding, moving it to `REMEDIATION_SUBMITTED` with a `remediation_note` and `submitted_by` stamped from `X-User-ID` (from any other state: `ERR_FINDING_NOT_OPEN`). An `IndependentAuditor` then verifies with a `decision`: `CONFIRM` moves `REMEDIATION_SUBMITTED` → `REMEDIATED`, while `REJECT` cycles the finding back to `OPEN` for another round; both stamp `verified_by`, both require `REMEDIATION_SUBMITTED` (`ERR_FINDING_NOT_SUBMITTED` otherwise), and both are subject to §2.10 — the verifier's `X-User-ID` must differ from `submitted_by`, else `ERR_SOD_VIOLATION`. Alternatively, an auditor may accept the risk of an `OPEN` finding outright, moving it to the terminal `ACCEPTED_RISK` with a `rationale` — but only for `LOW` or `MEDIUM` severity findings; `HIGH` and `CRITICAL` findings must be remediated, and the attempt yields `ERR_RISK_ACCEPTANCE_NOT_ALLOWED`.

An engagement closes from `REPORTED` once every one of its findings has reached `REMEDIATED` or `ACCEPTED_RISK`; open findings block the close with `ERR_ENGAGEMENT_HAS_OPEN_FINDINGS`. `CLOSED` is terminal for the engagement.

## 4. Endpoint Definitions

Operations that create new resources return `201 Created`; operations that modify an existing resource's state return `200 OK`. Read endpoints return `200 OK`. The complete request and response semantics for each operation are specified in §2 and §3; the table below is an index, not a full contract.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/aml/_clock/set_current_utc` | Set the logical clock | SystemAdmin |
| POST | `/aml/maintenance/run-daily-sweep` | Run the daily sweep (time-based transitions) | SystemAdmin |
| POST | `/aml/reps` | Create a registered rep | SystemAdmin |
| GET | `/aml/reps` | List reps | Any |
| GET | `/aml/reps/{id}` | Get a rep | Any |
| POST | `/aml/reps/{id}/suspend` | Suspend a rep | SystemAdmin |
| POST | `/aml/reps/{id}/reinstate` | Reinstate a rep | SystemAdmin |
| POST | `/aml/customers` | Create a customer (CIP record) | RegisteredRep |
| GET | `/aml/customers` | List customers | Any |
| GET | `/aml/customers/{id}` | Get a customer | Any |
| POST | `/aml/customers/{customerId}/identification-documents` | Submit a CIP identification document | RegisteredRep |
| GET | `/aml/identification-documents` | List identification documents | Any |
| GET | `/aml/identification-documents/{id}` | Get a document | Any |
| POST | `/aml/identification-documents/{id}/verify` | Verify a document | AMLAnalyst |
| POST | `/aml/identification-documents/{id}/reject` | Reject a document | AMLAnalyst |
| POST | `/aml/customers/{customerId}/beneficial-ownership-certifications` | Open a beneficial ownership certification | RegisteredRep |
| GET | `/aml/beneficial-ownership-certifications` | List certifications | Any |
| GET | `/aml/beneficial-ownership-certifications/{id}` | Get a certification | Any |
| POST | `/aml/beneficial-ownership-certifications/{certId}/owners` | Add a beneficial owner row | RegisteredRep |
| GET | `/aml/beneficial-owners` | List beneficial owners | Any |
| GET | `/aml/beneficial-owners/{id}` | Get a beneficial owner | Any |
| POST | `/aml/beneficial-ownership-certifications/{id}/certify` | Certify ownership | ComplianceOfficer |
| POST | `/aml/accounts` | Open-account request (initial risk computed) | RegisteredRep |
| GET | `/aml/accounts` | List accounts | Any |
| GET | `/aml/accounts/{id}` | Get an account | Any |
| POST | `/aml/accounts/{id}/approve` | Approve account opening | ComplianceOfficer |
| POST | `/aml/accounts/{id}/decline` | Decline account opening | ComplianceOfficer |
| POST | `/aml/accounts/{id}/restrict` | Restrict an open account | ComplianceOfficer |
| POST | `/aml/accounts/{id}/reinstate` | Reinstate a restricted account | ComplianceOfficer |
| POST | `/aml/accounts/{id}/close` | Close an account | ComplianceOfficer |
| POST | `/aml/accounts/{id}/risk-recalculations` | Run ongoing risk recalculation (OCC-guarded) | AMLAnalyst, ComplianceOfficer |
| POST | `/aml/accounts/{accountId}/edd-reviews` | Open an EDD review | AMLAnalyst |
| GET | `/aml/edd-reviews` | List EDD reviews | Any |
| GET | `/aml/edd-reviews/{id}` | Get an EDD review | Any |
| POST | `/aml/edd-reviews/{id}/begin` | Begin a review | AMLAnalyst |
| POST | `/aml/edd-reviews/{id}/complete` | Complete a review with a decision | ComplianceOfficer |
| POST | `/aml/accounts/{accountId}/transactions` | Post a transaction | RegisteredRep, OperationsAnalyst |
| GET | `/aml/transactions` | List transactions | Any |
| GET | `/aml/transactions/{id}` | Get a transaction | Any |
| POST | `/aml/transactions/{id}/reverse` | Reverse a posted or flagged transaction | OperationsAnalyst |
| POST | `/aml/transactions/{id}/clear` | Clear a flagged transaction | AMLAnalyst |
| POST | `/aml/monitoring-rules` | Create a transaction-monitoring rule | SystemAdmin |
| GET | `/aml/monitoring-rules` | List monitoring rules | Any |
| GET | `/aml/monitoring-rules/{id}` | Get a monitoring rule | Any |
| PATCH | `/aml/monitoring-rules/{id}` | Update a monitoring rule | SystemAdmin |
| POST | `/aml/monitoring-scans/run` | Run the monitoring scan over all enabled rules | AMLAnalyst |
| GET | `/aml/alerts` | List alerts | Any |
| GET | `/aml/alerts/{id}` | Get an alert | Any |
| POST | `/aml/alerts/{id}/begin-review` | Begin reviewing an alert | AMLAnalyst |
| POST | `/aml/alerts/{id}/close-no-action` | Close an alert with no action | AMLAnalyst |
| POST | `/aml/alerts/{id}/reopen` | Reopen a closed alert | AMLAnalyst |
| POST | `/aml/alerts/{id}/escalate` | Escalate an alert to a case | AMLAnalyst |
| POST | `/aml/aml-cases` | Manually open a case (OCC-guarded) | AMLAnalyst |
| GET | `/aml/aml-cases` | List cases | Any |
| GET | `/aml/aml-cases/{id}` | Get a case | Any |
| POST | `/aml/aml-cases/{id}/begin-investigation` | Begin investigating a case | AMLAnalyst |
| POST | `/aml/aml-cases/{id}/recommend-sar` | Recommend SAR filing | AMLAnalyst |
| POST | `/aml/aml-cases/{id}/decide-no-file` | Decide not to file | SAROfficer |
| POST | `/aml/aml-cases/{id}/close` | Close a case | SAROfficer |
| POST | `/aml/aml-cases/{id}/reopen` | Reopen a closed case | AMLAnalyst |
| POST | `/aml/sar-filings` | Draft a SAR | SAROfficer |
| GET | `/aml/sar-filings` | List SAR filings | Any |
| GET | `/aml/sar-filings/{id}` | Get a SAR filing | Any |
| POST | `/aml/sar-filings/{id}/file` | File a draft SAR | SAROfficer |
| POST | `/aml/sar-filings/{id}/continuing-reviews` | Record a continuing-activity review | SAROfficer |
| POST | `/aml/fincen-314a-requests` | Register a 314(a) list | ComplianceOfficer |
| GET | `/aml/fincen-314a-requests` | List 314(a) requests | Any |
| GET | `/aml/fincen-314a-requests/{id}` | Get a 314(a) request | Any |
| POST | `/aml/fincen-314a-requests/{id}/scan` | Run subject matching | ComplianceOfficer |
| POST | `/aml/fincen-314a-requests/{id}/submit-response` | Submit the 314(a) response | ComplianceOfficer |
| GET | `/aml/fincen-314a-matches` | List 314(a) matches | Any |
| GET | `/aml/fincen-314a-matches/{id}` | Get a 314(a) match | Any |
| POST | `/aml/fincen-314a-matches/{id}/confirm` | Confirm a match (restriction cascade) | ComplianceOfficer |
| POST | `/aml/fincen-314a-matches/{id}/mark-false-positive` | Mark a match false positive | ComplianceOfficer |
| POST | `/aml/fincen-314a-matches/{id}/resolve` | Resolve a confirmed match | ComplianceOfficer |
| POST | `/aml/accounts/{accountId}/certificate-deposits` | Intake a physical certificate | OperationsAnalyst |
| GET | `/aml/certificate-deposits` | List certificate deposits | Any |
| GET | `/aml/certificate-deposits/{id}` | Get a certificate deposit | Any |
| POST | `/aml/certificate-deposits/{id}/advance` | Advance the review pipeline one step | OperationsAnalyst |
| POST | `/aml/certificate-deposits/{id}/supplement` | Attach supplemental review information | OperationsAnalyst |
| POST | `/aml/certificate-deposits/{id}/decision` | Decide a ready deposit (OCC-guarded) | ComplianceOfficer |
| POST | `/aml/certificate-deposits/{id}/resubmit` | Resubmit a rejected deposit | OperationsAnalyst |
| POST | `/aml/lost-stolen-certificates` | Report a lost/stolen certificate | SystemAdmin |
| GET | `/aml/lost-stolen-certificates` | List lost/stolen registry entries | Any |
| GET | `/aml/lost-stolen-certificates/{id}` | Get a registry entry | Any |
| POST | `/aml/audit-engagements` | Plan an audit engagement | IndependentAuditor |
| GET | `/aml/audit-engagements` | List audit engagements | Any |
| GET | `/aml/audit-engagements/{id}` | Get an audit engagement | Any |
| POST | `/aml/audit-engagements/{id}/begin-fieldwork` | Begin fieldwork | IndependentAuditor |
| POST | `/aml/audit-engagements/{id}/issue-report` | Issue the engagement report | IndependentAuditor |
| POST | `/aml/audit-engagements/{id}/close` | Close an engagement | IndependentAuditor |
| POST | `/aml/audit-engagements/{engagementId}/findings` | Record a finding | IndependentAuditor |
| GET | `/aml/audit-findings` | List audit findings | Any |
| GET | `/aml/audit-findings/{id}` | Get an audit finding | Any |
| POST | `/aml/audit-findings/{id}/submit-remediation` | Submit remediation for a finding | ComplianceOfficer |
| POST | `/aml/audit-findings/{id}/verify-remediation` | Verify or reject submitted remediation | IndependentAuditor |
| POST | `/aml/audit-findings/{id}/accept-risk` | Accept the risk of a low/medium finding | IndependentAuditor |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this catalogue is an index.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_UNAUTHORIZED_ROLE` | 403 |
| `ERR_SOD_VIOLATION` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_ENUM` | 400 |
| `ERR_INVALID_DATE_RANGE` | 400 |
| `ERR_REP_NOT_FOUND` | 404 |
| `ERR_CUSTOMER_NOT_FOUND` | 404 |
| `ERR_ACCOUNT_NOT_FOUND` | 404 |
| `ERR_DOCUMENT_NOT_FOUND` | 404 |
| `ERR_CERTIFICATION_NOT_FOUND` | 404 |
| `ERR_OWNER_NOT_FOUND` | 404 |
| `ERR_EDD_REVIEW_NOT_FOUND` | 404 |
| `ERR_TRANSACTION_NOT_FOUND` | 404 |
| `ERR_RULE_NOT_FOUND` | 404 |
| `ERR_ALERT_NOT_FOUND` | 404 |
| `ERR_CASE_NOT_FOUND` | 404 |
| `ERR_SAR_FILING_NOT_FOUND` | 404 |
| `ERR_FINCEN_REQUEST_NOT_FOUND` | 404 |
| `ERR_MATCH_NOT_FOUND` | 404 |
| `ERR_DEPOSIT_NOT_FOUND` | 404 |
| `ERR_LOST_STOLEN_ENTRY_NOT_FOUND` | 404 |
| `ERR_ENGAGEMENT_NOT_FOUND` | 404 |
| `ERR_FINDING_NOT_FOUND` | 404 |
| `ERR_ACCOUNT_NOT_OPEN` | 409 |
| `ERR_ACCOUNT_RESTRICTED` | 409 |
| `ERR_ACCOUNT_CLOSED_TERMINAL` | 409 |
| `ERR_INVALID_LIFECYCLE_TRANSITION` | 409 |
| `ERR_POSTURE_SEVERE_BLOCKS` | 403 |
| `ERR_ACCOUNT_CLOSE_BLOCKED` | 409 |
| `ERR_MATCH_314A_UNRESOLVED` | 409 |
| `ERR_CRITICAL_CASE_OPEN` | 409 |
| `ERR_REP_SUSPENDED` | 409 |
| `ERR_DOCUMENT_NOT_VERIFIABLE` | 409 |
| `ERR_DOCUMENT_NOT_REJECTABLE` | 409 |
| `ERR_CIP_INCOMPLETE` | 409 |
| `ERR_CERTIFICATION_REQUIRES_LEGAL_ENTITY` | 400 |
| `ERR_CERTIFICATION_NOT_DRAFT` | 409 |
| `ERR_BENEFICIAL_OWNERSHIP_REQUIRED` | 422 |
| `ERR_EXCESSIVE_OWNERSHIP_TOTAL` | 422 |
| `ERR_OWNER_KYC_REQUIRED` | 422 |
| `ERR_CONTROL_PERSON_REQUIRED` | 422 |
| `ERR_PROHIBITED_TIER` | 403 |
| `ERR_EDD_APPROVAL_REQUIRED` | 409 |
| `ERR_EDD_REVIEW_NOT_ACTIONABLE` | 409 |
| `ERR_OVERLAPPING_EDD_REVIEW` | 409 |
| `ERR_TRANSACTION_NOT_REVERSIBLE` | 409 |
| `ERR_TRANSACTION_NOT_CLEARABLE` | 409 |
| `ERR_VELOCITY_LIMIT_EXCEEDED` | 422 |
| `ERR_RULE_DISABLED` | 409 |
| `ERR_ALERT_NOT_ACTIONABLE` | 409 |
| `ERR_ALERT_ACCOUNT_MISMATCH` | 400 |
| `ERR_CASE_NOT_ACTIONABLE` | 409 |
| `ERR_CASE_NOT_SAR_RECOMMENDED` | 409 |
| `ERR_CASE_HAS_OPEN_FILING` | 409 |
| `ERR_SAR_NOT_FILABLE` | 409 |
| `ERR_PRIOR_FILING_CASE_MISMATCH` | 400 |
| `ERR_FINCEN_REQUEST_NOT_SCANNABLE` | 409 |
| `ERR_MATCH_NOT_REVIEWABLE` | 409 |
| `ERR_FINCEN_RESPONSE_INCOMPLETE` | 409 |
| `ERR_DUPLICATE_314A_REQUEST` | 409 |
| `ERR_CERT_REPORTED_LOST_STOLEN` | 403 |
| `ERR_DUPLICATE_CERTIFICATE_NUMBER` | 409 |
| `ERR_DEPOSIT_NOT_ADVANCEABLE` | 409 |
| `ERR_DEPOSIT_NOT_DECIDABLE` | 409 |
| `ERR_DEPOSIT_NOT_RESUBMITTABLE` | 409 |
| `ERR_OVERLAPPING_AUDIT_ENGAGEMENT` | 409 |
| `ERR_ENGAGEMENT_NOT_ACTIVE` | 409 |
| `ERR_ENGAGEMENT_HAS_OPEN_FINDINGS` | 409 |
| `ERR_FINDING_NOT_OPEN` | 409 |
| `ERR_FINDING_NOT_SUBMITTED` | 409 |
| `ERR_RISK_ACCEPTANCE_NOT_ALLOWED` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_DUPLICATE_CRD_NUMBER` | 409 |
