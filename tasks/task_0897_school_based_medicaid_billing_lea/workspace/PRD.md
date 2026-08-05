# School-Based Medicaid Billing (LEA) API — Product Requirements Document

## 1. Introduction

Local Education Agencies (LEAs) that deliver Individualized Education Program (IEP) health services to Medicaid-enrolled students are entitled to reimbursement from Medicaid, but only when a long chain of compliance conditions is satisfied: the student is enrolled and consented, the service is authorized in an active IEP line, the delivering clinician holds a valid credential, the encounter is documented and independently verified, and the resulting claim is filed within program deadlines. This API is the system of record for that entire pipeline. It captures the students, providers, credentials, authorizations, and consents that establish eligibility; it records the service encounters that clinicians deliver; and it assembles those encounters into Medicaid claims that are submitted, adjudicated, denied, rebilled, or voided.

Beyond the interim fee-for-service (FFS) claiming stream, the platform also runs the Random-Moment Time Study (RMTS) that federal cost-settlement methodology requires. Sampled providers respond to randomly generated moments, coordinators code those responses into activity categories, and each closed study quarter yields a Medicaid-eligibility ratio. That ratio then drives an annual cost settlement that reconciles the LEA's certified program cost against the interim payments already received — a reconciliation that can produce either an additional federal share owed to the LEA or a recoupment owed back to the state.

The design is deliberately built around segregation of duties. No single actor may both deliver and verify a service, nor both submit and adjudicate a claim, nor both certify and settle a cost reconciliation. The sections below specify the global contracts every endpoint honors, the business workflows that move each entity through its lifecycle, and the exact error semantics the system guarantees.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the caller's role. If either header is absent, or `X-User-Role` does not name a role the system recognizes, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly four roles:

- **`ServiceProvider`** — the clinician who delivers services. A ServiceProvider self-logs and documents service sessions and responds to RMTS moments sampled for them. This role is entity-backed: when `X-User-Role` is `ServiceProvider`, `X-User-ID` is the `id` of the acting `Provider`. Ownership checks on any resource that references a provider compare that resource's `provider_id` to `X-User-ID`.
- **`BillingCoordinator`** — LEA billing staff who verify documented logs, and assemble, attach, submit, rebill, and void claims. When `X-User-Role` is `BillingCoordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`.
- **`MedicaidCoordinator`** — the LEA program administrator who manages students, providers, credentials, authorizations, and consents, runs the RMTS study, and creates and certifies cost settlements. When `X-User-Role` is `MedicaidCoordinator`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity.
- **`StateReviewer`** — the state Medicaid agency adjudicator who approves or denies submitted claims and settles certified cost settlements. When `X-User-Role` is `StateReviewer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.

All four roles may perform GET reads on every collection and may drive the logical clock. Beyond those shared capabilities, each role's exclusive operations are enumerated in the endpoint table of Section 4.

For the two operations a `ServiceProvider` self-performs — creating a service log and documenting it, and responding to a sampled moment — the caller's `X-User-ID` must equal the `provider_id` on the resource. When it does not, the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

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

All list endpoints accept two optional query parameters, `limit` and `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0 with a minimum of 0. A `limit` below 1 or above 100, or a negative `offset`, is a malformed request and is rejected with `ERR_VALIDATION` (HTTP 400). List results are ordered by `created_at` ascending. The `meta` block of a list response carries `limit`, `offset`, `total_count` (the full count of matching resources before the page window), and `has_more` (true when unreturned rows remain beyond the current window).

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource carries a server-minted `id` — a UUID with no type prefix — and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Every entity in this system also carries an `updated_at` timestamp (same format) and an integer `version`. The `version` starts at 1 when the resource is created and increments by one on every mutation that changes the resource; `updated_at` is refreshed to the current logical-clock instant on every such mutation. Whenever a computed field, a state, or a ledger figure on a resource changes as a result of an operation — including changes that ripple in from a cascade — that resource's `version` increments and its `updated_at` advances.

### 2.5. Request Validation Order and Precedence

When more than one validation could fire on a single request, the system evaluates them in a fixed precedence so the returned `error_id` is deterministic. The order is:

1. **Authentication** — headers present and `X-User-Role` a known role, else `ERR_UNAUTHENTICATED`.
2. **Authorization** — the caller's role is permitted for the endpoint per the role matrix, else `ERR_UNAUTHORIZED`.
3. **Path existence** — every resource named in the URL path exists, validated left-to-right in the order the identifiers appear, else the resource-specific not-found error.
4. **Body foreign-key existence** — every foreign key referenced in the request body exists (for example `student_id`, `provider_id`, `iep_authorization_id`, `rmts_quarter_id`, `service_log_id`), else the corresponding not-found error.

The resource-specific not-found errors, each HTTP 404, are: `ERR_STUDENT_NOT_FOUND` for a missing student, `ERR_PROVIDER_NOT_FOUND` for a missing provider, `ERR_CREDENTIAL_NOT_FOUND` for a missing credential, `ERR_AUTHORIZATION_NOT_FOUND` for a missing IEP authorization, `ERR_CONSENT_NOT_FOUND` for a missing parental consent, `ERR_SERVICE_LOG_NOT_FOUND` for a missing service log, `ERR_CLAIM_NOT_FOUND` for a missing claim, `ERR_QUARTER_NOT_FOUND` for a missing RMTS quarter, `ERR_MOMENT_NOT_FOUND` for a missing RMTS moment, and `ERR_SETTLEMENT_NOT_FOUND` for a missing cost settlement.
5. **Ownership** — for the ServiceProvider self-operations, `X-User-ID` equals the resource's `provider_id`, else `ERR_NOT_RESOURCE_OWNER`.
6. **State admissibility** — the target resource is in a state from which the requested transition is allowed, else `ERR_INVALID_STATE`.
7. **Claim submittability** — a submit targets a claim whose `status` is `DRAFT` or `DENIED`, else `ERR_CLAIM_NOT_SUBMITTABLE`.
8. **Log billability** — an attach targets a service log that is `VERIFIED` and unattached, else `ERR_LOG_NOT_BILLABLE`.
9. **Provider credentialing** — the delivering provider is credentialed, else `ERR_PROVIDER_NOT_CREDENTIALED`.
10. **Billing consent** — the student has granted billing consent, else `ERR_CONSENT_NOT_GRANTED`.
11. **Authorization active** — the IEP authorization is active, else `ERR_AUTHORIZATION_NOT_ACTIVE`.
12. **Service window** — the service date falls inside the authorization window, else `ERR_SERVICE_OUTSIDE_AUTH_WINDOW`.
13. **Provider double-booking** — the session does not overlap another of the provider's sessions, else `ERR_PROVIDER_DOUBLE_BOOKED`.
14. **Credential period overlap** — activation does not create overlapping active same-type credentials, else `ERR_CREDENTIAL_PERIOD_OVERLAP`.
15. **Timely filing** — the claim is within the filing deadline, else `ERR_TIMELY_FILING_EXCEEDED`.
16. **Billable units** — verification yields at least one unit, else `ERR_ZERO_BILLABLE_UNITS`.
17. **Encounter presence** — the claim has at least one attached encounter at submit, else `ERR_CLAIM_NO_ENCOUNTERS`.
18. **Sample sufficiency** — a quarter close has enough responded moments, else `ERR_INSUFFICIENT_SAMPLE`.
19. **Quarter closed** — a settlement create targets a closed quarter, else `ERR_QUARTER_NOT_CLOSED`.
20. **Stale version** — the settlement create's expected quarter version matches, else `ERR_STALE_QUARTER_VERSION`.

Independently of this ordering, any request whose body is malformed, is missing a required field, carries a value of the wrong type, supplies an out-of-domain enum value, or supplies invalid pagination parameters is rejected with `ERR_VALIDATION` (HTTP 400). The precise trigger conditions for each business validation are stated with the workflow it guards in Section 3; the concrete set of endpoints each rule applies to is called out there as well.

### 2.6. Monetary Precision, Unit Rounding, and Ratio Computation

All money in this system is expressed as an integer number of cents, and all billable service quantities as integer units. Wherever a division or scaling produces a fractional result that must land on an integer, the system rounds half-up (a value exactly halfway between two integers rounds to the larger integer). Two computations round to a fixed number of decimal places rather than to an integer: the Medicaid-eligibility ratio of an RMTS quarter is carried to four decimal places, rounded half-up. Every other rounding lands on a whole cent or a whole unit. The detailed formulas — how delivered units and charges are derived, how a claim's total is aggregated, how interim payments are fixed, how the eligibility ratio is computed, and how a cost settlement's nested allocation is carried out — appear in the Section 3 workflows they belong to. A cross-cutting rule that governs all of them: when a formula nests one rounding inside another, the rounding is applied at each nested step in the stated order, not deferred to the end.

### 2.7. Optimistic Concurrency on Quarter-Based Settlements

Creating a cost settlement is guarded by optimistic concurrency against the study quarter it reconciles. A settlement-create request must carry `expected_rmts_quarter_version`, a required input field holding the `version` of the target `RMTSQuarter` that the client last observed. If that value does not equal the quarter's current `version`, the create is rejected with `ERR_STALE_QUARTER_VERSION` (HTTP 412). This matters because a new settlement legitimately supersedes a prior one for the same closed quarter — corrections re-run the reconciliation — and each successful settlement create increments the quarter's `version` by one. When another writer has already created a settlement against the quarter since the current client last read it, that client's reconciliation basis is stale, and the concurrency check refuses the create rather than letting it proceed on outdated numbers. No other endpoint in the system takes a version field; only settlement creation participates in optimistic concurrency.

### 2.8. Cascading State Propagation and the Conservation Ledgers

Several operations mutate more than one entity. Where an operation triggers downstream state changes on related resources, every affected resource has its state, `version`, and `updated_at` updated as part of the same operation. The deepest such chain begins at student withdrawal and propagates through authorizations, service logs, and the claim ledgers; the individual hops are described in Sections 3.4, 3.5, and 3.9.

Two figures on each `Student` are conserved ledgers, meaning they are always kept equal to a defined sum over the student's related records rather than being independently editable. The first, `interim_paid_cents`, equals the sum of `interim_payment_cents` across the student's claims whose `status` is `PAID`; it is a money-conserved quantity, advanced when a claim is approved and reduced when a paid claim is voided. The second, `verified_service_units`, equals the sum of `delivered_units` across the student's service logs whose `status` is `VERIFIED`, `CLAIMED`, `PAID`, or `DENIED`; it is a unit-conserved quantity, advanced when a log is verified and reduced when a verified log is voided. Both are stored on the student as computed fields defaulting to 0.

### 2.9. The Logical Clock and Temporal Windows

The system runs on a logical clock rather than wall-clock time. On startup the clock reads exactly `2026-05-01T00:00:00Z` and holds that value until it is explicitly set; it never falls back to real time. Any of the four roles may advance or set the clock by supplying a target instant as `to_iso8601`. All timestamps the system records — `granted_date`, `revoked_date`, `submitted_date`, and every `created_at`/`updated_at` — are taken from this clock, and all deadline and validity-window comparisons (authorization windows, credential windows, timely filing, and the lazy expiration of authorizations and credentials) are evaluated against it. Authorization and credential windows are closed intervals from `effective_date` to `expiration_date` inclusive; a service session's `[start_time, end_time)` interval is half-open, so its start is inclusive and its end exclusive.

## 3. Business Logic & Workflows

### 3.1. Enrolling Students and Establishing Billing Eligibility

A `MedicaidCoordinator` registers a student by supplying the state `medicaid_id`, the student's `first_name` and `last_name`, `date_of_birth` (an ISO date in YYYY-MM-DD form), and the LEA-local `district_student_id`. The request may optionally include `medicaid_eligible`, a boolean flagging whether the student is currently Medicaid-enrolled; when omitted it defaults to true. A newly registered student begins in `status` `ACTIVE`, with both conservation ledgers — `interim_paid_cents` and `verified_service_units` — initialized to 0. A student's `status` moves only from `ACTIVE` to `WITHDRAWN`, and withdrawal is the terminal event described in Section 3.9. Reading a student returns the student together with its current ledger figures.

Before any service can be logged for billing, the student must have parental consent on file. A coordinator records a consent by supplying the covered `student_id`, the `consent_type` — either `BILLING` or `DISCLOSURE` — and `signed_by`, the name of the parent or guardian who signed. A consent opens in `status` `PENDING`, with `granted_date` and `revoked_date` both null. Granting a pending consent moves it to `GRANTED` and stamps `granted_date` with the current clock. Revoking a granted consent moves it to `REVOKED` and stamps `revoked_date`. A revoked consent can be re-granted, which returns it to `GRANTED`, re-stamps `granted_date`, and clears `revoked_date` back to null — the consent record cycles through re-consent rather than being recreated. The gate that service logging enforces is specifically a consent of type `BILLING` in `status` `GRANTED`; a `DISCLOSURE` consent, or a `BILLING` consent that is `PENDING` or `REVOKED`, does not satisfy it.

### 3.2. Providers and the Credential Lifecycle

A `MedicaidCoordinator` registers a provider with their `npi` (National Provider Identifier), `first_name`, `last_name`, and clinical `discipline`, which is one of `SLP`, `OT`, `PT`, `PSYCH`, `RN`, or `AUD`. A provider is created with `employment_status` set to `ACTIVE`, which is the only value that field takes.

Credentialing is tracked as a separate lifecycle. A coordinator adds a credential for a provider by supplying the `provider_id`, the `credential_type` — one of `STATE_LICENSE`, `NPI_ENROLLMENT`, or `MEDICAID_ENROLLMENT` — the `license_number`, and the validity window's `effective_date` and `expiration_date` (both ISO dates, interpreted as a closed inclusive interval). A credential opens in `status` `PENDING`. Activating a pending credential moves it to `ACTIVE`; activation is refused with `ERR_INVALID_STATE` if the credential is not currently `PENDING` or `SUSPENDED`. Activation carries an additional guard: it must not produce two `ACTIVE` credentials for the same `provider_id` and the same `credential_type` whose closed validity windows overlap. Two closed windows overlap when they share any point, so windows that merely touch at an endpoint are treated as overlapping; a violating activation is rejected with `ERR_CREDENTIAL_PERIOD_OVERLAP` (HTTP 409). An active credential may be suspended, moving it to `SUSPENDED` (the coordinator may include a `reason`), and a suspended credential may be reinstated by activating it again, which returns it to `ACTIVE` under the same non-overlap guard. Separately, the system lazily expires an active credential: whenever a credential is consulted to gate a claim submission, if the logical-clock date has advanced strictly past its `expiration_date`, it is treated as `EXPIRED`. Credentials can be listed and filtered by `provider_id` and by `status`.

### 3.3. Authorizing IEP Service Lines

Each billable service line is authorized on an `IEPAuthorization`. A coordinator creates one by supplying the `student_id` it authorizes, the `service_type` — one of `SPEECH_THERAPY`, `OCCUPATIONAL_THERAPY`, `PHYSICAL_THERAPY`, `PSYCH_COUNSELING`, `NURSING`, or `AUDIOLOGY` — the billing `procedure_code` (an HCPCS/CPT code such as 92507), the `unit_minutes` that constitute one billable unit for the procedure, the Medicaid fee-schedule `unit_rate_cents` per billable unit, the IEP-authorized `authorized_minutes_per_session`, the authorized `sessions_per_week`, and the window's `effective_date` and `expiration_date`. An authorization opens in `status` `DRAFT`. Activating it moves it to `ACTIVE`, the only status in which it will admit service logs. An active authorization can be discontinued, moving it to `DISCONTINUED` and triggering the cascade of Section 3.9. Like credentials, an active authorization is lazily expired: whenever it is consulted to gate a service-log create, if the clock date is strictly past its `expiration_date`, it is treated as `EXPIRED`. Both `DISCONTINUED` and `EXPIRED` are terminal. Authorizations can be listed and filtered by `student_id` and `status`.

From an authorization one can derive the *provisional* billable units for a session — the units expected before delivery is known. The provisional figure is `authorized_minutes_per_session` divided by `unit_minutes`, rounded half-up to the nearest whole number. This provisional variant uses the authorized minutes rather than the minutes actually delivered, is derivable at any time from the authorization alone, and is never persisted; only the delivered figure computed at verification (Section 3.4) is stored on a service log.

### 3.4. Logging, Documenting, and Verifying Service Encounters

A `ServiceProvider` records a delivered session as a service log, supplying the `iep_authorization_id` of the authorized line delivered, their own `provider_id`, the served `student_id`, the `service_date`, the session `start_time` and `end_time`, the `delivered_minutes` actually delivered, and optionally the `group_size` (the number of students in the session, defaulting to 1 for an individual session). Because a provider self-logs, the caller's `X-User-ID` must equal the supplied `provider_id`, or the create is refused with `ERR_NOT_RESOURCE_OWNER`. Creation runs a chain of business guards in this order: the delivering provider must have an `ACTIVE` credential whose closed window covers the `service_date`, else `ERR_PROVIDER_NOT_CREDENTIALED` (HTTP 422); the student must have a `BILLING` consent in `status` `GRANTED`, else `ERR_CONSENT_NOT_GRANTED` (HTTP 422); the authorization must be in `status` `ACTIVE`, else `ERR_AUTHORIZATION_NOT_ACTIVE` (HTTP 422); the `service_date` must fall within the authorization's closed `[effective_date, expiration_date]` window, else `ERR_SERVICE_OUTSIDE_AUTH_WINDOW` (HTTP 422); and the new session must not overlap another service log of the same provider. Overlap is judged on the half-open `[start_time, end_time)` interval, so two sessions that merely abut — one ending exactly when the next begins — do not conflict, whereas any shared interior instant does; a conflict yields `ERR_PROVIDER_DOUBLE_BOOKED` (HTTP 409). A new log opens in `status` `LOGGED` with `claim_id` null.

The same provider then documents the log, attaching the `documentation_note`; this moves the log from `LOGGED` to `DOCUMENTED` and, like the create, is an owner-only action. A separate `BillingCoordinator` performs encounter capture by verifying the documented log — the two steps are segregated across roles by design. Verification advances the log from `DOCUMENTED` to `VERIFIED` and computes its billable figures: `delivered_units` is `delivered_minutes` divided by the authorization's `unit_minutes`, rounded half-up to the nearest whole number, and `charge_cents` is `delivered_units` multiplied by the authorization's `unit_rate_cents`. Verification is refused with `ERR_ZERO_BILLABLE_UNITS` (HTTP 422) when the computed `delivered_units` would be 0 — that is, the delivered minutes must round to at least one unit. On a successful verify, the student's `verified_service_units` ledger is increased by the log's `delivered_units`.

Should the documentation be inadequate, the coordinator may instead return the documented log for correction, which moves it from `DOCUMENTED` back to `LOGGED`, records the `return_reason`, and clears the `documentation_note` to null so the provider must re-document. A verified log that has not yet been attached to a claim (its `claim_id` is still null) may be voided by a coordinator, moving it to the terminal `VOID` state; because that log had contributed to the ledger, voiding it decreases the student's `verified_service_units` by its `delivered_units`, reversing the earlier increase. Service logs can be listed and filtered by `iep_authorization_id`, `provider_id`, `student_id`, `claim_id`, and `status`.

### 3.5. Assembling, Submitting, and Adjudicating Claims

A `BillingCoordinator` opens a claim for a student by supplying the `student_id` and the `service_month` billing period (in YYYY-MM form). A claim opens in `status` `DRAFT` with `total_charge_cents` 0 and `attached_log_count` 0. The coordinator attaches verified encounters to the draft by supplying the `service_log_id` of a log to add. Attaching advances that log from `VERIFIED` to `CLAIMED`, but only when the log is `VERIFIED` and unattached; an attach against a log that is not verified-and-unattached is rejected with `ERR_LOG_NOT_BILLABLE` (HTTP 409). The log must also belong to the same student the claim bills — its `student_id` must equal the claim's `student_id`. On a successful attach the log's `claim_id` is set to the claim, and the claim's `total_charge_cents` and `attached_log_count` are recomputed.

The claim's `total_charge_cents` is the sum, over its attached logs whose `status` is `CLAIMED`, `PAID`, or `DENIED`, of each log's charge; verified-but-detached logs and voided logs are excluded. That sum is computed by rounding each log individually first: for every attached log, divide its `delivered_minutes` by its authorization's `unit_minutes` and round half-up to whole units, multiply by that authorization's `unit_rate_cents` to get the log's charge in cents, and only then add the per-log charges together. The rounding is done per log before summing — the system never sums delivered minutes across logs and rounds once at the end. The `attached_log_count` is simply the number of attached logs in those same three statuses.

Submitting a claim advances it from `DRAFT` to `SUBMITTED` and stamps `submitted_date` with the clock. A submit is only admissible when the claim's `status` is `DRAFT` or `DENIED`; a submit against any other status is rejected with `ERR_CLAIM_NOT_SUBMITTABLE` (HTTP 409). Submission also enforces three business conditions: the claim must have at least one attached encounter (`attached_log_count` of at least 1), else `ERR_CLAIM_NO_ENCOUNTERS` (HTTP 422); for every attached log, the delivering provider must hold an `ACTIVE` credential whose closed window covers that log's `service_date`, else `ERR_PROVIDER_NOT_CREDENTIALED` (HTTP 422); and the claim must be within the filing deadline. Timely filing compares the current clock date against the latest `service_date` among the attached logs: the difference must be at most 365 days. A difference of exactly 365 days still files successfully, and 366 days fails, at which point the submit is rejected with `ERR_TIMELY_FILING_EXCEEDED` (HTTP 422).

A `StateReviewer` adjudicates a submitted claim by supplying an `outcome` of `APPROVE` or `DENY`. On `APPROVE`, the claim moves to `PAID`; its `interim_payment_cents` is fixed to equal its `total_charge_cents` at that moment (the full fee-schedule allowed amount — this interim FFS reimbursement is the fee-schedule charge itself, and is the counterpart to the cost-settled federal share computed later, which is cost-based and generally differs); the student's `interim_paid_cents` ledger is increased by that interim payment; and every attached log advances from `CLAIMED` to `PAID`. On `DENY`, the reviewer must supply a `denial_reason` — one of `MISSING_CONSENT`, `CREDENTIAL_LAPSED`, `DUPLICATE_CLAIM`, or `DOC_INCOMPLETE`; the claim moves to `DENIED`, the `denial_reason` is recorded, and every attached log moves from `CLAIMED` to `DENIED`. Claims can be listed and filtered by `student_id` and `status`.

### 3.6. Denials, Rebilling, and Voids

A denied claim can be rebilled. Rebilling is the same submit action applied to a claim in `status` `DENIED`: it advances the claim back to `SUBMITTED`, increments `rebill_count` by one, re-stamps `submitted_date`, clears `denial_reason` back to null, and moves every attached log from `DENIED` back to `CLAIMED`. A rebill re-runs the same credential-coverage and timely-filing guards that a first submission does.

Claims can also be voided by a `BillingCoordinator`, with behavior depending on the claim's state at the time. Voiding a `DRAFT` claim detaches each attached log — moving it from `CLAIMED` back to `VERIFIED` and clearing its `claim_id` to null — and zeroes the claim's `total_charge_cents` and `attached_log_count`. Voiding a `DENIED` claim likewise detaches its logs, moving each from `DENIED` back to `VERIFIED`, and zeroes the same totals. Voiding a `PAID` claim additionally recoups money: the student's `interim_paid_cents` ledger is decreased by the claim's `interim_payment_cents`, each attached log moves from `PAID` back to `VERIFIED` and is detached, and `total_charge_cents`, `interim_payment_cents`, and `attached_log_count` are all zeroed. In every case the claim lands in the terminal `VOID` state. A `SUBMITTED` claim cannot be voided; only `DRAFT`, `DENIED`, and `PAID` claims are voidable.

### 3.7. The Random-Moment Time Study

The RMTS underpins cost settlement. A `MedicaidCoordinator` opens a study period by supplying its `fiscal_quarter` label (for example, 2026-Q1). A quarter opens in `status` `OPEN` with `total_moments`, `responded_moments`, `medicaid_eligible_moments`, and `medicaid_eligibility_ratio` all 0. Moments may be generated, responded to, and coded only while the quarter is `OPEN`.

The coordinator generates a sampled moment by supplying the `rmts_quarter_id`, the sampled `provider_id`, and the `moment_timestamp`. A moment opens in `status` `GENERATED`, and generating it increments the quarter's `total_moments`. The sampled provider responds to the moment by recording a free-text `activity_response`, which advances it from `GENERATED` to `RESPONDED`; responding is an owner-only action, so the caller's `X-User-ID` must equal the moment's `provider_id`, and the quarter must still be `OPEN`. The coordinator then codes the responded moment by assigning an `activity_category` — one of `DIRECT_MEDICAL`, `MEDICAL_ADMIN`, `GENERAL_ADMIN`, `NON_MEDICAL`, or `NON_RESPONSE` — which advances it from `RESPONDED` to `CODED`. Coding computes the boolean `is_medicaid_eligible_moment`, which is true exactly when the assigned `activity_category` is `DIRECT_MEDICAL` or `MEDICAL_ADMIN`, and recomputes the quarter's `responded_moments` and `medicaid_eligible_moments`. The quarter's `responded_moments` is the count of its moments in `status` `CODED`, and `medicaid_eligible_moments` is the count of those CODED moments whose `is_medicaid_eligible_moment` is true. Moments can be listed and filtered by `rmts_quarter_id` and `provider_id`.

Closing a quarter advances it from `OPEN` to `CLOSED` and fixes its `medicaid_eligibility_ratio`. The ratio is `medicaid_eligible_moments` divided by `responded_moments`, rounded half-up to four decimal places, and while the quarter is open it remains 0. A close is permitted only when `responded_moments` is at least 4; a close attempted with fewer than 4 responded moments is rejected with `ERR_INSUFFICIENT_SAMPLE` (HTTP 422), where exactly 4 passes and 3 fails.

### 3.8. Cost Settlement and Reconciliation

Once a quarter is closed, a `MedicaidCoordinator` creates a cost settlement to reconcile the LEA's certified program cost against interim payments. The create supplies the `rmts_quarter_id` of the closed quarter, the `certified_cost_cents` (total certified LEA program cost for the pool), the `iep_ratio_bps` (the IEP special-education ratio in basis points, so 4000 means 40%), the `fmap_bps` (the Federal Medical Assistance Percentage in basis points, so 5000 means 50%), the LEA-supplied `interim_paid_cents` already reimbursed for the pool, and the `expected_rmts_quarter_version` that guards the create under optimistic concurrency (Section 2.7). The linked quarter must be in `status` `CLOSED`, else the create is rejected with `ERR_QUARTER_NOT_CLOSED` (HTTP 422).

On creation the settlement computes its figures in a fixed nested order, rounding half-up at each step. Starting from the quarter's fixed `medicaid_eligibility_ratio`, the Medicaid-allocated cost is `certified_cost_cents` multiplied by that ratio, rounded half-up to whole cents. The `gross_medicaid_cost_cents` is that Medicaid-allocated cost multiplied by `iep_ratio_bps` and divided by 10000, rounded half-up to whole cents — the Medicaid-and-IEP allocated cost before applying the federal match. The `federal_share_cents` is `gross_medicaid_cost_cents` multiplied by `fmap_bps` and divided by 10000, rounded half-up to whole cents; this is the cost-settled reimbursement. Finally, `net_settlement_cents` is `federal_share_cents` minus the supplied `interim_paid_cents`, and may be negative — a negative net settlement represents a recoupment the LEA owes back to the state. This cost-settled federal share is the dual-variant counterpart to the interim FFS payments: computed on a cost basis, it generally differs in amount from the fee-schedule interim reimbursement for the same services. A new settlement opens in `status` `CALCULATED`.

Settlement finalization is segregated: the LEA certifies and the state settles. The `MedicaidCoordinator` certifies a calculated settlement, advancing it from `CALCULATED` to `CERTIFIED`, and a `StateReviewer` then settles the certified settlement, advancing it from `CERTIFIED` to the terminal `SETTLED`. Settlements can be listed and filtered by `rmts_quarter_id` and `status`.

### 3.9. Withdrawals and the Depth-3 Cascade

Withdrawing a student is the deepest state propagation in the system. A `MedicaidCoordinator` withdraws an active student, moving the student from `ACTIVE` to the terminal `WITHDRAWN`. As a first cascade hop, every `IEPAuthorization` of that student whose `status` is `ACTIVE` is discontinued, moving from `ACTIVE` to `DISCONTINUED`. Discontinuing an authorization — whether reached through this withdrawal cascade or invoked directly on an active authorization — is itself the second hop: every service log referencing that authorization whose `status` is `LOGGED`, `DOCUMENTED`, or `VERIFIED` is voided, moving to the terminal `VOID`. That void is the third hop and carries the ledger consequence: a voided log that had been `VERIFIED` decreases the student's `verified_service_units` by its `delivered_units`, exactly as a direct void would. Logs already attached to claims (those in `CLAIMED`, `PAID`, or `DENIED`) are not swept up by this cascade; only the non-terminal, not-yet-billed logs are voided. Every resource touched along the chain has its `version` incremented and its `updated_at` advanced as part of the single withdrawal operation.

## 4. Endpoint Definitions

Endpoints that create a new resource return HTTP 201; all other successful operations, including state transitions and reads, return HTTP 200. Request and response bodies are not restated here — reconstruct them from the workflow narratives in Section 3.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/_clock/set_current_utc` | Set the server logical clock | MedicaidCoordinator, BillingCoordinator, StateReviewer, ServiceProvider |
| POST | `/sbmb/students` | Register a student | MedicaidCoordinator |
| GET | `/sbmb/students/{studentId}` | Get a student with computed ledgers | MedicaidCoordinator, BillingCoordinator, StateReviewer, ServiceProvider |
| POST | `/sbmb/students/{studentId}/withdraw` | Withdraw a student (depth-3 cascade) | MedicaidCoordinator |
| POST | `/sbmb/providers` | Register a provider | MedicaidCoordinator |
| GET | `/sbmb/providers/{providerId}` | Get a provider | MedicaidCoordinator, BillingCoordinator, StateReviewer, ServiceProvider |
| POST | `/sbmb/provider-credentials` | Add a credential for a provider | MedicaidCoordinator |
| GET | `/sbmb/provider-credentials/{credentialId}` | Get a credential | MedicaidCoordinator, BillingCoordinator, StateReviewer, ServiceProvider |
| GET | `/sbmb/provider-credentials` | List credentials, filterable by provider and status | MedicaidCoordinator, BillingCoordinator, StateReviewer, ServiceProvider |
| POST | `/sbmb/provider-credentials/{credentialId}/activate` | Activate or reinstate a credential | MedicaidCoordinator |
| POST | `/sbmb/provider-credentials/{credentialId}/suspend` | Suspend an active credential | MedicaidCoordinator |
| POST | `/sbmb/iep-authorizations` | Create an IEP service authorization line | MedicaidCoordinator |
| GET | `/sbmb/iep-authorizations/{authorizationId}` | Get an authorization | MedicaidCoordinator, BillingCoordinator, StateReviewer, ServiceProvider |
| GET | `/sbmb/iep-authorizations` | List authorizations, filterable by student and status | MedicaidCoordinator, BillingCoordinator, StateReviewer, ServiceProvider |
| POST | `/sbmb/iep-authorizations/{authorizationId}/activate` | Activate an authorization | MedicaidCoordinator |
| POST | `/sbmb/iep-authorizations/{authorizationId}/discontinue` | Discontinue an authorization (depth-2 cascade) | MedicaidCoordinator |
| POST | `/sbmb/parental-consents` | Record a parental consent | MedicaidCoordinator |
| GET | `/sbmb/parental-consents/{consentId}` | Get a consent | MedicaidCoordinator, BillingCoordinator, StateReviewer, ServiceProvider |
| GET | `/sbmb/parental-consents` | List consents, filterable by student and status | MedicaidCoordinator, BillingCoordinator, StateReviewer, ServiceProvider |
| POST | `/sbmb/parental-consents/{consentId}/grant` | Grant or re-grant a consent | MedicaidCoordinator |
| POST | `/sbmb/parental-consents/{consentId}/revoke` | Revoke a granted consent | MedicaidCoordinator |
| POST | `/sbmb/service-logs` | Log a delivered service session | ServiceProvider |
| GET | `/sbmb/service-logs/{serviceLogId}` | Get a service log | MedicaidCoordinator, BillingCoordinator, StateReviewer, ServiceProvider |
| GET | `/sbmb/service-logs` | List service logs, filterable by authorization, provider, student, claim, status | MedicaidCoordinator, BillingCoordinator, StateReviewer, ServiceProvider |
| POST | `/sbmb/service-logs/{serviceLogId}/document` | Attach documentation to a logged session | ServiceProvider |
| POST | `/sbmb/service-logs/{serviceLogId}/verify` | Verify a documented log (encounter capture) | BillingCoordinator |
| POST | `/sbmb/service-logs/{serviceLogId}/return` | Return a documented log for correction | BillingCoordinator |
| POST | `/sbmb/service-logs/{serviceLogId}/void` | Void an unattached logged/documented/verified log | BillingCoordinator |
| POST | `/sbmb/claims` | Open a claim | BillingCoordinator |
| GET | `/sbmb/claims/{claimId}` | Get a claim | MedicaidCoordinator, BillingCoordinator, StateReviewer, ServiceProvider |
| GET | `/sbmb/claims` | List claims, filterable by student and status | MedicaidCoordinator, BillingCoordinator, StateReviewer, ServiceProvider |
| POST | `/sbmb/claims/{claimId}/attach` | Attach a verified service log to a draft claim | BillingCoordinator |
| POST | `/sbmb/claims/{claimId}/submit` | Submit a draft claim or rebill a denied claim | BillingCoordinator |
| POST | `/sbmb/claims/{claimId}/adjudicate` | Approve or deny a submitted claim | StateReviewer |
| POST | `/sbmb/claims/{claimId}/void` | Void a draft, denied, or paid claim | BillingCoordinator |
| POST | `/sbmb/rmts-quarters` | Open an RMTS study period | MedicaidCoordinator |
| GET | `/sbmb/rmts-quarters/{quarterId}` | Get a quarter with computed ratio and version | MedicaidCoordinator, BillingCoordinator, StateReviewer, ServiceProvider |
| POST | `/sbmb/rmts-quarters/{quarterId}/close` | Close a quarter and fix its eligibility ratio | MedicaidCoordinator |
| POST | `/sbmb/rmts-moments` | Generate a sampled moment in an open quarter | MedicaidCoordinator |
| GET | `/sbmb/rmts-moments/{momentId}` | Get a moment | MedicaidCoordinator, BillingCoordinator, StateReviewer, ServiceProvider |
| GET | `/sbmb/rmts-moments` | List moments, filterable by quarter and provider | MedicaidCoordinator, BillingCoordinator, StateReviewer, ServiceProvider |
| POST | `/sbmb/rmts-moments/{momentId}/respond` | Sampled provider records their activity | ServiceProvider |
| POST | `/sbmb/rmts-moments/{momentId}/code` | Coordinator codes a response into a category | MedicaidCoordinator |
| POST | `/sbmb/cost-settlements` | Create a cost settlement against a closed quarter (OCC) | MedicaidCoordinator |
| GET | `/sbmb/cost-settlements/{settlementId}` | Get a cost settlement | MedicaidCoordinator, BillingCoordinator, StateReviewer, ServiceProvider |
| GET | `/sbmb/cost-settlements` | List cost settlements, filterable by quarter and status | MedicaidCoordinator, BillingCoordinator, StateReviewer, ServiceProvider |
| POST | `/sbmb/cost-settlements/{settlementId}/certify` | LEA certifies the settlement | MedicaidCoordinator |
| POST | `/sbmb/cost-settlements/{settlementId}/settle` | State finalizes the settlement | StateReviewer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_NOT_RESOURCE_OWNER | 403 |
| ERR_VALIDATION | 400 |
| ERR_STUDENT_NOT_FOUND | 404 |
| ERR_PROVIDER_NOT_FOUND | 404 |
| ERR_CREDENTIAL_NOT_FOUND | 404 |
| ERR_AUTHORIZATION_NOT_FOUND | 404 |
| ERR_CONSENT_NOT_FOUND | 404 |
| ERR_SERVICE_LOG_NOT_FOUND | 404 |
| ERR_CLAIM_NOT_FOUND | 404 |
| ERR_QUARTER_NOT_FOUND | 404 |
| ERR_MOMENT_NOT_FOUND | 404 |
| ERR_SETTLEMENT_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_CLAIM_NOT_SUBMITTABLE | 409 |
| ERR_LOG_NOT_BILLABLE | 409 |
| ERR_PROVIDER_NOT_CREDENTIALED | 422 |
| ERR_CONSENT_NOT_GRANTED | 422 |
| ERR_AUTHORIZATION_NOT_ACTIVE | 422 |
| ERR_SERVICE_OUTSIDE_AUTH_WINDOW | 422 |
| ERR_PROVIDER_DOUBLE_BOOKED | 409 |
| ERR_CREDENTIAL_PERIOD_OVERLAP | 409 |
| ERR_TIMELY_FILING_EXCEEDED | 422 |
| ERR_ZERO_BILLABLE_UNITS | 422 |
| ERR_CLAIM_NO_ENCOUNTERS | 422 |
| ERR_INSUFFICIENT_SAMPLE | 422 |
| ERR_QUARTER_NOT_CLOSED | 422 |
| ERR_STALE_QUARTER_VERSION | 412 |
