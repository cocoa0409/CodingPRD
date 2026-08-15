# Livestock Health Certificate Interstate API — Product Requirements Document

## 1. Introduction

Moving livestock across state lines is one of the most regulated routine activities in American agriculture. Every consignment of cattle, swine, poultry, sheep, goats, or horses that crosses a border must travel under a Certificate of Veterinary Inspection signed by an accredited veterinarian, must satisfy a destination-state entry matrix that can demand specific diagnostic tests and vaccination lead times, and must often carry an entry permit whose number the destination state tracks. Layered on top of that paperwork is the disease-control machinery of the state veterinarian's office: outbreak zones that freeze movement out of an affected county, quarantine orders that pin a premises in place, and laboratory results that can flip a herd's standing from routine to infected in a single posting.

This document specifies a program-level API for a state veterinarian office that administers that entire lifecycle electronically. The system maintains the premises registry and the accredited-veterinarian roster, publishes the destination-state entry-requirement matrix, records laboratory tests and their results, shepherds each certificate from draft through review, issuance, transmission, and possible voiding, issues and adjusts movement permits, tracks individual shipments from scheduling through delivery for traceback, and coordinates outbreak zones and quarantine orders with automatic cascades that hold certificates, suspend permits, and restore them when the emergency passes. A segregated set of operator roles — program administrators, state veterinarian officers, accredited veterinarians, laboratory technicians, and read-only state auditors — share the platform, with deliberate segregation-of-duties controls where public health demands a second pair of eyes.

Two design commitments shape everything that follows. First, the system runs on a **logical clock** rather than wall-clock time, so certificate validity windows, test ages, quarantine expirations, and outbreak-zone windows are all evaluated against a single controllable instant. Second, every mutation and every cascade it triggers completes atomically within the request: a positive test result, for example, infects the premises, auto-creates a quarantine order, and rejects pending certificates in one indivisible step. Implementers should read §2 for the system-wide contracts and §3 for the business workflows before consulting the endpoint and error catalogues in §4 and §5.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming the operator's role. A request missing either header, or carrying an empty value for either, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400) before any other check runs. Once the headers are accepted, the role is matched against the endpoint's authorized role list; a role not listed for that endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

The platform recognizes exactly five roles, spelled as follows:

- **ProgramAdmin** — the office administrator who maintains reference data: the premises registry, the veterinarian registry, the destination-state entry-requirement matrix, and the logical clock. When `X-User-Role` is `ProgramAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- **StateVetOfficer** — the state veterinarian office official who reviews, issues, rejects, voids, and transmits certificates, issues and adjusts movement permits, declares and manages outbreak zones, issues and lifts quarantine orders, suspends veterinarians, accredits premises, and records transmission acknowledgements and failures. When `X-User-Role` is `StateVetOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does record it — for example as `issued_by_user_id` on a `QuarantineOrder` at issuance — and the segregation-of-duties check at quarantine lift compares the lifting operator's `X-User-ID` against that recorded value, but no ownership check compares it to an entity `id`.
- **AccreditedVet** — the accredited veterinarian who performs inspections: drafting and submitting certificates, requesting movement permits, and scheduling, departing, arriving, and cancelling movement records. When `X-User-Role` is `AccreditedVet`, `X-User-ID` is the `id` of the acting `Veterinarian`; a request under this role whose `X-User-ID` matches no registered `Veterinarian` row is rejected with `ERR_VETERINARIAN_NOT_FOUND` (HTTP 404). Ownership checks on any resource that references a `Veterinarian` compare the resource's foreign-key field to `X-User-ID` — directly for a certificate's `vet_id`, and through the permit-to-certificate chain for movement records (see §3.5).
- **LabTechnician** — the diagnostic laboratory operator who registers tests and reports results. When `X-User-Role` is `LabTechnician`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- **StateAuditor** — a read-only auditor for traceback and compliance review. When `X-User-Role` is `StateAuditor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.

All read endpoints are shared across all five roles. Write capabilities are exclusive to the roles named above, as detailed per workflow in §3 and summarized per endpoint in §4.

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

List endpoints accept two query parameters. `limit` defaults to 10, must be at least 1, and may not exceed 100. `offset` defaults to 0. List responses are sorted by `created_at` ascending, and the `meta` block of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more` so that a client can page deterministically through the full result set.

### 2.4. The Logical Clock and Lazy Expirations

The server evaluates all time-dependent rules — certificate validity, test and vaccination ages, permit windows, outbreak-zone windows, and quarantine expiry — against a single **logical clock**, never against wall-clock time. At startup, before any administrative action, the logical clock reads exactly 2026-08-01T00:00:00Z. A `ProgramAdmin`-only test-driving capability advances the logical clock to a supplied instant carried in the `to_iso8601` request field and answers with the resulting `current_utc`; once advanced, the clock stays where it was set.

Two expirations are **lazily materialized**: a certificate whose `valid_until` has passed, and a quarantine order whose `end_at` has passed, do not change state in the background. Instead, the state change materializes on the first read or write that touches the record after the logical clock has advanced beyond the threshold — a certificate read evaluates the `LAPSED` check before responding, and a premises read first materializes the `EXPIRED` evaluation of that premises' quarantine orders. Advancing the logical clock therefore never mutates anything by itself; it arms the transitions that the next read or write will apply.

### 2.5. Validation Order of Operations

Every request passes through a fixed pipeline of validation layers, evaluated in the order below; the first layer that fails determines the error the client sees.

1. **Header presence.** `X-User-ID` and `X-User-Role` must be present and non-empty, else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Applies to all endpoints.
2. **Role authorization.** The presented role must appear in the endpoint's authorized role list, else `ERR_FORBIDDEN` (HTTP 403). Applies to all endpoints.
3. **Request-body schema.** Required fields must be present, types must be valid, enum values must be in range, `head_count` values must be greater than zero, `end_at` must be later than `start_at`, `effective_until` must be later than `effective_from`, `valid_until` must not be earlier than `valid_from`, a test's `test_date` must not be after the certificate's `inspection_date`, and `inspection_date` must not be after the logical clock. Violations yield `ERR_VALIDATION` (HTTP 400) on any endpoint that takes a request body.
4. **Existence.** Path identifiers must exist and are validated strictly left-to-right along the URL hierarchy; body-supplied foreign keys — `origin_premises_id`, `test_record_id`, `premises_id`, `certificate_id`, `permit_id` — must also resolve to existing rows. A missing resource yields its specific not-found error (for example `ERR_PREMISES_NOT_FOUND` or `ERR_PERMIT_NOT_FOUND`, HTTP 404; the full catalogue appears in §5).
5. **Ownership.** Certificate submission and revision, and movement-record creation, departure, arrival, and cancellation, are restricted to the veterinarian of record; violations yield `ERR_NOT_CERTIFICATE_OWNER` (HTTP 403). The exact ownership chains are defined in §3.4 and §3.5.
6. **State preconditions.** The target resource must be in the state the transition requires — the certificate, permit, movement, zone, quarantine, test, transmission, premises-accreditation, and veterinarian-suspension state machines in §3 each carry their own conflict error (HTTP 409).
7. **Safety gates**, evaluated in this order: (a) the acting veterinarian's credential must be current, else `ERR_VET_NOT_CURRENT`; (b) the origin premises' disease standing must be neither `QUARANTINE_HOLD` nor `INFECTED`, else `ERR_PREMISES_DISEASE_HOLD`; (c) the relied-upon test result must be `NEGATIVE`, else `ERR_TEST_NOT_QUALIFYING`; (d) no `ACTIVE` outbreak zone may cover the origin county and species at the logical clock, else `ERR_OUTBREAK_MOVEMENT_RESTRICTION`. Which subset applies to which operation is enumerated in §3; all four are HTTP 422.
8. **Matrix and linkage integrity**, evaluated in this order: (a) an `ACTIVE` entry-requirement row whose half-open window covers the inspection date must exist for the destination state and species, else `ERR_NO_ACTIVE_ENTRY_REQUIREMENT`; (b) the certificate's species must equal the origin premises' species (and, for quarantine orders, the order's species must equal the premises' species), else `ERR_PREMISES_SPECIES_MISMATCH`; (c) the relied-upon test record must match the origin premises, the species, and the matrix row's test type, else `ERR_TEST_RECORD_MISMATCH`. All three are HTTP 422.
9. **Temporal-window rules**, evaluated in this order: (a) test whole-day age within the matrix allowance, else `ERR_TEST_VALIDITY_EXPIRED`; (b) vaccination whole-day age meeting the matrix minimum, else `ERR_VACCINATION_WINDOW_VIOLATION`; (c) the permit window contained in certificate validity, else `ERR_PERMIT_WINDOW_OUTSIDE_CVI_VALIDITY`; (d) the movement instant inside the permit window and not after certificate expiry, else `ERR_MOVEMENT_OUTSIDE_PERMIT_WINDOW`. All four are HTTP 422.
10. **Constraint rules.** Inventory and headroom limits (`ERR_HEAD_COUNT_EXCEEDS_INVENTORY`, `ERR_PERMIT_HEADROOM_EXCEEDED`, `ERR_ALLOCATION_BELOW_CERTIFICATE_HEADCOUNT`, `ERR_ALLOCATION_BELOW_CONSUMED`), window-overlap rules (`ERR_ZONE_WINDOW_OVERLAP`, `ERR_REQUIREMENT_WINDOW_OVERLAP`, `ERR_QUARANTINE_WINDOW_CONFLICT`), the quarantine minimum-gap rule (`ERR_QUARANTINE_MIN_GAP_VIOLATION`), and the quarantine segregation-of-duties rule (`ERR_SEGREGATION_OF_DUTIES`) are enforced at the operations enumerated in §3. Window-overlap violations return HTTP 409; the headroom, allocation, minimum-gap, and segregation violations return HTTP 422 except `ERR_SEGREGATION_OF_DUTIES`, which returns HTTP 403.
11. **Optimistic concurrency.** Stale-version rejections (`ERR_STALE_PERMIT_VERSION`, `ERR_STALE_REQUIREMENT_VERSION`, HTTP 412) run last, on the two version-guarded write operations described in §2.8.

### 2.6. Common Resource Properties

Every resource in the system carries an `id` minted by the server as a UUID with no type prefix, a `created_at` timestamp in ISO 8601 UTC with three fractional digits, an `updated_at` timestamp of the same format refreshed on every mutation, and a `version` integer that starts at its initial value on creation and increments by one on every mutation of that resource. All entities in this program — premises, veterinarians, entry requirements, test records, certificates, movement permits, movement records, outbreak zones, quarantine orders, and transmission audits — carry the full common set.

When a cascade mutates a related entity — holding a premises when a zone escalates, blocking a certificate, suspending a permit, cancelling a movement record — that mutation bumps the affected entity's `version` and refreshes its `updated_at` exactly as a direct write would. Computed fields such as headrooms, fee totals, and current inventory are re-derived from source data on read; they do not themselves constitute mutations.

### 2.7. Money, Precision, and Rounding

All monetary amounts are integers denominated in whole cents; the certificate issuance fee is computed with integer arithmetic and has no rounding step. Movement fees use fractional per-head rates, and each movement record's fee is rounded **half up to whole cents** before any aggregation takes place. The rounding order is pinned: per-line rounding first, summation second — summing unrounded products and rounding once at the end is a rejected interpretation. Animal counts are whole animals everywhere; day-age computations use whole days as defined in §2.9; and datetime comparisons are made at second precision.

### 2.8. Optimistic Concurrency Control

Exactly two write operations are version-guarded; no other endpoint accepts a version field.

Amending an entry-requirement matrix row — the operation that adjusts `test_validity_days`, `vaccination_required`, `vaccination_min_days_before_inspection`, `permit_required`, or `effective_until` on a requirement — must carry `expected_requirement_version` as a non-optional input holding the row's `version` the client last observed. If the row's current `version` differs — because another amendment landed in between — the request is rejected with `ERR_STALE_REQUIREMENT_VERSION` (HTTP 412). A successful amendment increments the requirement's `version` by one. Because a requirement row remains `ACTIVE` after any amendment, a second sequential amend would otherwise succeed silently; the version check is the only detection of the stale write.

Adjusting an issued movement permit — the operation that changes `allocated_head_count` or `valid_until` — must likewise carry `expected_permit_version` holding the permit's last observed `version`. A mismatch with the permit's current `version` is rejected with `ERR_STALE_PERMIT_VERSION` (HTTP 412), and a successful adjustment increments the permit's `version` by one and recomputes its headrooms and fee totals. Here too the permit remains `ISSUED` after adjustment, so a second sequential adjust would legitimately succeed under product semantics and only the version check exposes the stale write.

### 2.9. Certificate Validity and Whole-Day Age Conventions

Issuance stamps a certificate with `issued_at` equal to the logical clock at that instant and computes `valid_until` as exactly 30 days after `issued_at`. A certificate lapses only when the logical clock is strictly later than `valid_until`; sitting exactly at the boundary does not lapse it.

Window containment uses inclusive bounds. A permit may be issued only when its `valid_from` is at or after the certificate's `issued_at` and its `valid_until` is at or before the certificate's `valid_until`. A movement — whether being scheduled against its `planned_ship_date` or departing at the logical clock instant — must satisfy all of the following: the instant is at or after the permit's `valid_from`, at or before the permit's `valid_until`, and at or before the certificate's `valid_until`.

Test and vaccination ages are measured in **whole days**: the elapsed seconds between the sample's `test_date` (or the `vaccination_date`) and the certificate's `inspection_date`, divided by the number of seconds in a day, rounded down. A test qualifies when its whole-day age at inspection is at least zero and at most the matrix row's `test_validity_days`, with the upper bound inclusive. A vaccination qualifies when its whole-day age at inspection is at least the matrix row's `vaccination_min_days_before_inspection`, again inclusive.

### 2.10. Issuance Sequences and Audit Identifiers

Two identifier sequences are global and monotonic across the whole program. Issuing a certificate mints its `cvi_number` in the form `CVI-<origin state code>-<six-digit sequence>` — for example `CVI-TX-000001`. Issuing a movement permit mints its `permit_number` in the form `EP-<destination state code>-<six-digit sequence>` — for example `EP-KS-000001`. Both remain null until the respective issuance occurs. Every electronic transmission of a certificate is recorded with a `payload_digest` holding the lowercase hexadecimal SHA-256 (64 hex characters) of the canonical transmitted payload, so the destination state and any auditor can verify byte-for-byte what was sent.

## 3. Business Logic & Workflows

### 3.1. Reference Data: Premises, Veterinarians, and the Entry-Requirement Matrix

Before any certificate can move an animal, a `ProgramAdmin` builds the program's reference data. Registering a **premises** captures the operation's `name`, the `county` where the premises sits (this county value is what outbreak-zone coverage later keys on), the two-letter `state_code`, the `species_code` of the primary species on the operation — one of `CATTLE`, `SWINE`, `POULTRY`, `SHEEP_GOAT`, or `EQUINE` — and the `initial_head_count`, an animal census that must be zero or greater and is immutable after creation. The premises begins life with `disease_status` `MONITORED` unless the administrator supplies a different standing at registration, and its `current_head_count` is initialized to `initial_head_count`. Disease standing is one of `ACCREDITED_FREE`, `MONITORED`, `QUARANTINE_HOLD`, or `INFECTED`; later system transitions may overwrite it per the state machines in §3.6 and §3.7. A `StateVetOfficer` may grant accredited-free standing to a premises by accrediting it, which succeeds only while `disease_status` is `MONITORED` and no `ACTIVE` quarantine order covers that premises and species — otherwise the attempt is rejected with `ERR_PREMISES_NOT_ACCREDITABLE` (HTTP 409) — and sets `disease_status` to `ACCREDITED_FREE`.

Registering a **veterinarian** captures the practitioner's `full_name`, the state-issued `accreditation_number` (unique across veterinarians), and `accreditation_expires_at`, the ISO 8601 UTC instant the accreditation lapses. A new veterinarian starts with `status` `ACTIVE`. The derived flag `is_credential_current` recomputes on every read: it is true exactly when `status` is `ACTIVE` and `accreditation_expires_at` is at or after the logical clock. A `StateVetOfficer` may suspend a veterinarian whose `status` is `ACTIVE`; suspending an already-`SUSPENDED` veterinarian is rejected with `ERR_VET_NOT_SUSPENDABLE` (HTTP 409). Suspension does not rewrite history, but it immediately blocks that veterinarian's certificate submissions and any issuance performed under their credential, which fail the credential check with `ERR_VET_NOT_CURRENT` (HTTP 422).

The **entry-requirement matrix** is the destination-state rulebook. Each row records a `destination_state_code`, the `species_code` it governs, the required `test_type` — one of `BRUCELLOSIS`, `TUBERCULOSIS`, `EIA`, `PULLORUM`, or `NONE` — and `test_validity_days`, the maximum whole-day age (inclusive) at which a test still qualifies at inspection, which must be greater than zero. When `vaccination_required` is true, a certificate against this row must carry a `vaccination_date`, and `vaccination_min_days_before_inspection` (defaulting to 0, never negative) sets the minimum whole-day lead time, inclusive. The `permit_required` flag records whether the destination state demands an entry permit for that species. Each row is effective over a half-open window: `effective_from` is inclusive, `effective_until` is exclusive, and a null `effective_until` means the row is open-ended; when `effective_until` is provided it must be later than `effective_from`. Rows begin `ACTIVE`, and may later be `RETIRED`. A `ProgramAdmin` amends an existing row through the version-guarded operation described in §2.8, which may adjust `test_validity_days`, `vaccination_required`, `vaccination_min_days_before_inspection`, `permit_required`, and `effective_until`; changing `effective_until` re-evaluates the window-overlap rule below.

Two rows fight for the same slot when their half-open windows overlap while both are `ACTIVE` for the same combination of `destination_state_code`, `species_code`, and `test_type` — creating such a row, or amending `effective_until` into such an overlap, is rejected with `ERR_REQUIREMENT_WINDOW_OVERLAP` (HTTP 409). The matrix is queryable by all roles with optional `destination_state_code`, `species_code`, and `status` filters plus the standard `limit` and `offset` pagination parameters. Looking up a matrix row by an identifier that does not exist yields `ERR_ENTRY_REQUIREMENT_NOT_FOUND` (HTTP 404).

### 3.2. Laboratory Testing and the Infection Cascade

A `LabTechnician` registers each diagnostic test drawn on a premises by submitting the `premises_id`, the `species_code` tested, the `test_type` performed (one of `BRUCELLOSIS`, `TUBERCULOSIS`, `EIA`, or `PULLORUM`), the `test_date` on which the sample was drawn — this date anchors every validity computation — and the laboratory's `lab_reference` accession number. A body-supplied `premises_id` that matches no registered premises is rejected with `ERR_PREMISES_NOT_FOUND` (HTTP 404). The record is born with `result` `RESULT_PENDING`, and the test-records listing under a premises supports the usual `limit` and `offset` pagination.

Reporting the result is a one-way door: the `result` submitted by the `LabTechnician` moves the record from `RESULT_PENDING` to either `NEGATIVE` or `POSITIVE`, and a record that has already resolved rejects further result postings with `ERR_TEST_RECORD_NOT_PENDING` (HTTP 409).

A `NEGATIVE` result is quiet — it simply qualifies the test for certificate use. A `POSITIVE` result detonates the infection cascade, atomically within the same request:

1. The sampled premises' `disease_status` becomes `INFECTED`.
2. Unless an `ACTIVE` quarantine order already covers that premises and species, the system auto-creates a `QuarantineOrder` whose `start_at` is the logical clock, whose `end_at` is exactly 30 days later, whose `disease_code` is derived from the test's type, whose `reason` is the literal string `AUTO_POSITIVE_TEST:` followed by the test record's id, and whose `issued_by_user_id` is the literal string `system`.
3. Every certificate whose `origin_premises_id` is the newly infected premises and whose `status` is `DRAFT` or `PENDING_REVIEW` is rejected to `REJECTED` with `reject_reason` set to `AUTO_POSITIVE_TEST`. This is the certificate state machine's system-driven `DRAFT → REJECTED` and `PENDING_REVIEW → REJECTED` branch, distinct from officer rejection.

Certificates already `ISSUED` or beyond are not touched by this cascade; the disease-hold gates in §3.4 and §3.5 stop them from doing further work.

### 3.3. Certificate Drafting and Revision

An `AccreditedVet` drafts a Certificate of Veterinary Inspection by supplying the `origin_premises_id` of the consignment's origin, the two-letter `destination_state_code`, the `species_code` certified, the `head_count` covered (greater than zero, and editable only while the certificate is `DRAFT`), the `inspection_date` of the veterinary inspection (which may not be later than the logical clock), and optionally a `consignment_description` in free text. Unless the matched matrix row's `test_type` is `NONE`, the draft must also name the `test_record_id` of the qualifying test relied upon; when the matrix row requires vaccination, the draft must carry a `vaccination_date`. Body-supplied foreign keys that do not resolve are rejected with the corresponding not-found error — `ERR_PREMISES_NOT_FOUND` for a bad `origin_premises_id`, `ERR_TEST_RECORD_NOT_FOUND` for a bad `test_record_id`.

The draft is born in `status` `DRAFT`. The creating veterinarian's identity is stamped automatically: `vet_id` is set to the caller's `X-User-ID`, and any client-supplied value for it is ignored. The certificate's fee fields stay null until their respective triggers — `provisional_fee_cents` until submission, `final_fee_cents` until issuance — and `cvi_number`, `issued_at`, and `valid_until` likewise remain null until issued.

Officer rejection is not the end of the road. The owning veterinarian may return a `REJECTED` certificate to `DRAFT` by revising it; revision clears `reject_reason` to null so the corrected draft resubmits cleanly. Attempting revision from any state other than `REJECTED` is rejected with `ERR_CERTIFICATE_NOT_REVISABLE` (HTTP 409). This revision loop — `DRAFT → PENDING_REVIEW → REJECTED → DRAFT` — may cycle as often as needed while the certificate remains voidable of further progress.

### 3.4. Review, Issuance, and the Issuance Fee

Submission moves a `DRAFT` certificate to `PENDING_REVIEW`. Only the veterinarian of record may submit: the caller's `X-User-ID` must equal the certificate's `vet_id`, else `ERR_NOT_CERTIFICATE_OWNER` (HTTP 403). Submitting from any state other than `DRAFT` yields `ERR_CERTIFICATE_NOT_SUBMITTABLE` (HTTP 409). Submission then runs the deepest validation battery in the program, evaluated in the pipeline order of §2.5 — credential first, disease hold second, test result third, then matrix existence, species agreement, and test linkage, then the temporal windows, then inventory:

- The acting veterinarian's `is_credential_current` must be true (`ERR_VET_NOT_CURRENT`, HTTP 422).
- The origin premises' `disease_status` must be neither `QUARANTINE_HOLD` nor `INFECTED` (`ERR_PREMISES_DISEASE_HOLD`, HTTP 422).
- When the matrix row's `test_type` is not `NONE`, the relied-upon test's `result` must be `NEGATIVE`; a `RESULT_PENDING` or `POSITIVE` test fails with `ERR_TEST_NOT_QUALIFYING` (HTTP 422).
- An `ACTIVE` entry-requirement row must exist for the certificate's `destination_state_code` and `species_code` whose half-open window covers the `inspection_date`, else `ERR_NO_ACTIVE_ENTRY_REQUIREMENT` (HTTP 422).
- The certificate's `species_code` must equal the origin premises' `species_code`, else `ERR_PREMISES_SPECIES_MISMATCH` (HTTP 422).
- The `test_record_id` must name a test record drawn on the same origin premises, of the same species, and of the matrix row's `test_type`, else `ERR_TEST_RECORD_MISMATCH` (HTTP 422).
- The test's whole-day age at inspection (per §2.9) must not exceed the row's `test_validity_days`; an over-age test fails with `ERR_TEST_VALIDITY_EXPIRED` (HTTP 422). A `test_date` after the `inspection_date` is not even well-formed and fails earlier as `ERR_VALIDATION` (HTTP 400).
- When the row's `vaccination_required` is true, a `vaccination_date` must be present and its whole-day age at inspection must be at least `vaccination_min_days_before_inspection`, else `ERR_VACCINATION_WINDOW_VIOLATION` (HTTP 422).
- The certificate's `head_count` must not exceed the origin premises' `current_head_count`, else `ERR_HEAD_COUNT_EXCEEDS_INVENTORY` (HTTP 422).

A passing submission computes and stores the **provisional issuance fee** in `provisional_fee_cents`. The fee is a base of 2500 cents, plus a per-head rate multiplied by the certificate's `head_count` — 150 cents for `CATTLE`, 90 for `SWINE`, 25 for `POULTRY`, 60 for `SHEEP_GOAT`, 200 for `EQUINE` — plus a surcharge of 1000 cents when the origin premises' `disease_status` is `MONITORED` at the moment of submission, with the total capped at 20000 cents (an `ACCREDITED_FREE` premises pays no surcharge, and a `QUARANTINE_HOLD` or `INFECTED` premises never reaches this point because the disease-hold gate fires first).

Issuance is the `StateVetOfficer`'s act, moving `PENDING_REVIEW` to `ISSUED`. Attempting issuance — or rejection — from any other state yields `ERR_CERTIFICATE_NOT_PENDING_REVIEW` (HTTP 409). Issuance re-runs the first two safety gates: the acting veterinarian's credential must still be current (`ERR_VET_NOT_CURRENT`), and the origin premises must still be free of disease hold (`ERR_PREMISES_DISEASE_HOLD`). A successful issuance mints the `cvi_number` per §2.10, stamps `issued_at` with the logical clock, sets `valid_until` thirty days out per §2.9, and computes the **final issuance fee** into `final_fee_cents` using the same formula re-evaluated at issuance time. The provisional-to-final comparison is deliberate: if the origin premises moved from `MONITORED` to `ACCREDITED_FREE` between submission and issuance, the final fee comes out exactly 1000 cents lower than the provisional quote.

An officer may instead reject a certificate under review, recording the request's `reason_code` into `reject_reason`. Certificates in `ISSUED`, `TRANSMITTED`, or `ENTRY_BLOCKED` may be voided by an officer, recording the request's `reason` into `void_reason`; voiding from any other state is rejected with `ERR_CERTIFICATE_NOT_VOIDABLE` (HTTP 409). Voiding detonates its own cascade, atomically: every movement permit belonging to the certificate whose `status` is `REQUESTED`, `ISSUED`, or `SUSPENDED` becomes `VOIDED`; on each such permit, every movement record in `SCHEDULED` or `IN_TRANSIT` becomes `CANCELLED`; and for each record cancelled out of `IN_TRANSIT`, the origin premises' `current_head_count` is restored by that record's `head_count`. Headrooms and `total_movement_fees_cents` recompute on the permits that remain. `VOID` and `LAPSED` are terminal; a lapsed certificate — one the logical clock has moved strictly past `valid_until`, materialized lazily per §2.4 — is also terminal, and when an `ENTRY_BLOCKED` certificate lapses its `pre_block_status` is cleared to null as part of the transition.

Certificates are listed with filters supporting traceback: `vet_id`, `origin_premises_id`, `test_record_id`, `status`, and `destination_state_code`, alongside `limit` and `offset`. Reading a single certificate materializes any pending lazy `LAPSED` evaluation first. A certificate id that does not exist yields `ERR_CERTIFICATE_NOT_FOUND` (HTTP 404).

### 3.5. Entry Permits and Shipment Tracking

Once a certificate stands `ISSUED` or `TRANSMITTED`, the veterinarian of record may request a **movement permit** against it, supplying the `certificate_id`, an `allocated_head_count` greater than zero, and an inclusive movement window from `valid_from` to `valid_until` (the end must not precede the start). An unknown `certificate_id` yields `ERR_PERMIT_NOT_FOUND`'s sibling `ERR_CERTIFICATE_NOT_FOUND`; the permit itself is born `REQUESTED`, with `permit_number` null until issuance.

Permit issuance is the officer's act and runs four preconditions: the permit must be `REQUESTED` and its backing certificate must be `ISSUED` or `TRANSMITTED` — either failure is `ERR_PERMIT_NOT_ISSUABLE` (HTTP 409); the `allocated_head_count` must be at least the certificate's `head_count`, else `ERR_ALLOCATION_BELOW_CERTIFICATE_HEADCOUNT` (HTTP 422); and the permit window must sit inside certificate validity per §2.9, else `ERR_PERMIT_WINDOW_OUTSIDE_CVI_VALIDITY` (HTTP 422). Issuance mints the `permit_number` per §2.10. Officers may later adjust an `ISSUED` permit's `allocated_head_count` or `valid_until` through the version-guarded operation of §2.8; adjusting a permit that is not `ISSUED` fails with `ERR_PERMIT_NOT_ADJUSTABLE` (HTTP 409), and the new allocation may not drop below the head count already consumed — the allocation minus the `committed_headroom` — or the request fails with `ERR_ALLOCATION_BELOW_CONSUMED` (HTTP 422).

Two headroom figures are exposed on every permit read. `committed_headroom` is the `allocated_head_count` minus the summed `head_count` of the permit's movement records in `SCHEDULED`, `IN_TRANSIT`, or `DELIVERED`; this is the figure that gates scheduling. `projected_headroom` subtracts only records in `IN_TRANSIT` or `DELIVERED`, treating merely-scheduled shipments as not yet consumed — so a permit allocated for 20 animals with one scheduled record of 6 reports a `committed_headroom` of 14 and a `projected_headroom` of 20. `total_movement_fees_cents` sums the per-record fees over records in `SCHEDULED`, `IN_TRANSIT`, or `DELIVERED`; cancelled records contribute nothing.

Scheduling a **movement record** is the veterinarian's act, and ownership is checked through the chain: the caller's `X-User-ID` must equal the `vet_id` of the certificate backing the record's permit, else `ERR_NOT_CERTIFICATE_OWNER`. The request names the `permit_id` (an unknown one yields `ERR_PERMIT_NOT_FOUND`, HTTP 404), the shipment's `head_count`, the out-of-state `destination_name` in free text, an optional `destination_county`, and the `planned_ship_date`. Scheduling requires the permit to be `ISSUED` (`ERR_PERMIT_NOT_ISSUED`, HTTP 409 — this is also what blocks new scheduling while a permit sits `SUSPENDED`), the origin premises free of disease hold (`ERR_PREMISES_DISEASE_HOLD`), no `ACTIVE` outbreak zone covering the origin county and species at the logical clock (`ERR_OUTBREAK_MOVEMENT_RESTRICTION`, HTTP 422), the `planned_ship_date` inside the permit window and not after the certificate's `valid_until` (`ERR_MOVEMENT_OUTSIDE_PERMIT_WINDOW`), and the shipment's `head_count` no greater than the permit's `committed_headroom` (`ERR_PERMIT_HEADROOM_EXCEEDED`, HTTP 422). A scheduled record is born `SCHEDULED`, and its `movement_fee_cents` is computed once, at creation: the record's `head_count` multiplied by the per-head movement rate for the species resolved through the permit to its certificate — 137.5 cents for `CATTLE`, 62.5 for `SWINE`, 10.25 for `POULTRY`, 45.5 for `SHEEP_GOAT`, 210.75 for `EQUINE` — rounded half up to whole cents per the pinned order of §2.7. The permit's headrooms and fee total recompute immediately.

Departure advances a record from `SCHEDULED` to `IN_TRANSIT` under the same ownership rule. Departing requires the record be `SCHEDULED` and the permit be `ISSUED` — state failures yield `ERR_MOVEMENT_NOT_ADVANCEABLE` and `ERR_PERMIT_NOT_ISSUED` respectively (HTTP 409). The departure instant (the logical clock) must lie inside the permit window and not after certificate expiry (`ERR_MOVEMENT_OUTSIDE_PERMIT_WINDOW`), the origin premises must be free of disease hold (`ERR_PREMISES_DISEASE_HOLD`), no `ACTIVE` zone may cover the origin (`ERR_OUTBREAK_MOVEMENT_RESTRICTION`), and the shipment's `head_count` must not exceed the premises' `current_head_count` (`ERR_HEAD_COUNT_EXCEEDS_INVENTORY`). Departure stamps `departed_at` with the logical clock and decrements the origin premises' `current_head_count` by the record's `head_count`.

Arrival advances `IN_TRANSIT` to `DELIVERED`, stamping `arrived_at` with the logical clock — the traceback timestamp — and departing from any state other than the required one, or arriving from a state other than `IN_TRANSIT`, yields `ERR_MOVEMENT_NOT_ADVANCEABLE`. Cancellation is permitted from either `SCHEDULED` or `IN_TRANSIT` and moves the record to `CANCELLED`; from any other state it yields `ERR_MOVEMENT_NOT_ADVANCEABLE`. Cancelling a scheduled record simply releases its committed headroom. Cancelling an in-transit record additionally restores the origin premises' `current_head_count` by the record's `head_count`, a compensating restore that conserves inventory across a depart-then-cancel sequence. Both forms recompute the permit's headrooms and fee total.

Inventory itself is defined derivation-first: a premises' `current_head_count` equals its `initial_head_count` minus the summed `head_count` of every movement record whose chain — record to permit to certificate — leads back to that premises as origin, counting only records in `IN_TRANSIT` or `DELIVERED`. Scheduled records have not moved inventory; cancelled records are excluded entirely. Permits attached to a certificate, and movement records under a permit, are both listable with `limit` and `offset`; a movement-record id that does not exist yields `ERR_MOVEMENT_RECORD_NOT_FOUND` (HTTP 404).

### 3.6. Outbreak Zones and the Hold/Restore Cascade

A `StateVetOfficer` declares an **outbreak zone** over a `county` and two-letter `state_code`, naming the `disease_code` under watch — one of `AVIAN_INFLUENZA`, `BRUCELLOSIS`, `TUBERCULOSIS`, `EIA`, `PULLORUM`, `VESICULAR_STOMATITIS`, or `PSEUDORABIES` — the `species_code` covered, and the declared `severity` of `LOW`, `MODERATE`, or `HIGH`. The zone's half-open window runs from `effective_from` (inclusive) to `effective_until` (exclusive, null for open-ended, and strictly later than `effective_from` when provided). Declaration is rejected with `ERR_ZONE_WINDOW_OVERLAP` (HTTP 409) when the new zone's window would overlap another zone in `MONITORING`, `ACTIVE`, or `CONTAINED` for the same combination of county, disease, and species; zones that have reached `RESOLVED` no longer block. A zone is born `MONITORING`, and a zone id that does not exist yields `ERR_OUTBREAK_ZONE_NOT_FOUND` (HTTP 404).

Escalation moves a zone from `MONITORING` or `CONTAINED` to `ACTIVE` — the re-escalation loop lets a contained outbreak flare back — and from any other state is rejected with `ERR_ZONE_INVALID_TRANSITION` (HTTP 409). Escalation fires a three-link cascade, atomically:

1. Every premises whose `county` and `species_code` match the zone and whose `disease_status` is not already `INFECTED` drops to `QUARANTINE_HOLD`.
2. Every certificate originating at a just-held premises whose `status` is `ISSUED` or `TRANSMITTED` becomes `ENTRY_BLOCKED`, remembering where it came from in `pre_block_status` (`ISSUED` or `TRANSMITTED` respectively; the field is null at all other times).
3. Every movement permit in `ISSUED` whose certificate was just blocked becomes `SUSPENDED`.

Suspension freezes but does not destroy: a `SUSPENDED` permit blocks new scheduling and departures through `ERR_PERMIT_NOT_ISSUED`, yet its `SCHEDULED` records are left untouched pending reinstatement.

Containment moves an `ACTIVE` zone to `CONTAINED` and is a paperwork-only gesture: all holds stay exactly where they are, and only resolution releases them. Resolution is allowed from `MONITORING` or `CONTAINED` — attempting escalate, contain, or resolve from an incompatible state always yields `ERR_ZONE_INVALID_TRANSITION`. Resolving from `MONITORING` has nothing to unwind. Resolving from `CONTAINED` runs the three-link restore cascade: every premises held by this zone (county and species match, `disease_status` `QUARANTINE_HOLD`) returns to `MONITORED`, but only when no other `ACTIVE` zone covers it and no `ACTIVE` quarantine order covers it; every certificate in `ENTRY_BLOCKED` whose origin premises was just restored returns to the state saved in `pre_block_status` — back to `ISSUED` or back to `TRANSMITTED` — and clears `pre_block_status` to null; and every permit in `SUSPENDED` whose certificate was just restored returns to `ISSUED`. Premises restore is evaluated first, so certificate and permit restoration always sees the final premises standing.

### 3.7. Quarantine Orders and Segregation of Duties

A `StateVetOfficer` may also quarantine a single premises directly, supplying `premises_id`, `species_code` (which must equal the premises' own species, else `ERR_PREMISES_SPECIES_MISMATCH`), `disease_code`, a closed interval from `start_at` to `end_at` (both inclusive, and the end must be strictly later than the start), and a free-text `reason`. The issuing officer's identity is stamped into `issued_by_user_id` from `X-User-ID` — or carries the literal string `system` on the auto-created orders of §3.2. Creation pushes the premises' `disease_status` to `QUARANTINE_HOLD` unless the premises is already `INFECTED`, in which case infection stands. An unknown premises id yields `ERR_PREMISES_NOT_FOUND`; an unknown order id yields `ERR_QUARANTINE_ORDER_NOT_FOUND`.

Two spacing rules discipline new orders. The new order's closed interval may not overlap an `ACTIVE` order for the same premises and species — overlap yields `ERR_QUARANTINE_WINDOW_CONFLICT` (HTTP 409). And a new order may not begin less than 14 days after the most recent `LIFTED` or `EXPIRED` order's `end_at` for that premises and species — a shorter gap yields `ERR_QUARANTINE_MIN_GAP_VIOLATION` (HTTP 422).

An order ends in one of two ways. When the logical clock moves strictly past `end_at`, the order becomes `EXPIRED` on the next read or write that touches it, per the lazy rule of §2.4. An officer may instead lift an `ACTIVE` order — lifting anything else yields `ERR_QUARANTINE_NOT_ACTIVE` (HTTP 409) — but never their own: if the lifter's `X-User-ID` equals the order's `issued_by_user_id`, the request is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403), and a second officer must perform the lift. Either ending re-evaluates the premises identically: when the premises sits in `QUARANTINE_HOLD` and no other `ACTIVE` order covers that premises and species and no `ACTIVE` outbreak zone covers its county and species, the premises returns to `MONITORED`; an `INFECTED` premises stays `INFECTED` regardless. Quarantine orders for a premises are listable with `limit` and `offset`.

### 3.8. Electronic Transmission and the Audit Trail

Issuance is not complete until the destination state has the certificate in hand. Transmitting a certificate — an officer act permitted while the certificate is `ISSUED` or `TRANSMITTED`, and rejected from any other state with `ERR_CERTIFICATE_NOT_TRANSMITTABLE` (HTTP 409) — does not itself change the certificate's status. Instead it appends a new **transmission audit** row carrying the `certificate_id`, the `destination_state_code` copied from the certificate at transmission time, the requested `channel` (one of `XML_GATEWAY`, `EMAIL`, or `PORTAL`), and the `payload_digest` of §2.10. The row is born `QUEUED`, and the trail is append-only — old rows are never rewritten. Transmitting answers 201 with the created audit row.

The destination's acknowledgement, recorded by an officer, moves a `QUEUED` audit to `ACKNOWLEDGED`, stamps `acknowledged_at` with the logical clock, and bubbles the certificate upward: the certificate named by the audit's `certificate_id` transitions from `ISSUED` to `TRANSMITTED` (a no-op if it is already `TRANSMITTED`). Recording a failure instead moves the audit from `QUEUED` to `FAILED` and stores the request's `failure_reason` on the row (the field is null otherwise); the certificate stays `ISSUED`, and a later transmission simply appends a fresh `QUEUED` row. Acting on an audit that is no longer `QUEUED` — either way — yields `ERR_TRANSMISSION_NOT_ADVANCEABLE` (HTTP 409), and an unknown audit id yields `ERR_TRANSMISSION_AUDIT_NOT_FOUND` (HTTP 404). The full audit trail for a certificate is listable by all roles with `limit` and `offset`, giving the `StateAuditor` a complete, tamper-evident record of what was sent where, when it was acknowledged, and how each attempt ended.

## 4. Endpoint Definitions

All endpoints are mounted under the `/api` prefix, with the single exception of the test-driving clock endpoint. Creating a new resource answers HTTP 201; state transitions, modifications, and reads answer HTTP 200. Errors follow the envelope and catalogue of §2.2 and §5.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/_clock/set_current_utc` | Advance the server logical clock to the supplied instant; startup default is exactly 2026-08-01T00:00:00Z and the server never falls back to wall-clock time | ProgramAdmin |
| POST | `/api/premises` | Register a livestock premises | ProgramAdmin |
| GET | `/api/premises/{id}` | Read a premises (materializes lazy EXPIRED evaluation of its quarantine orders first) | ProgramAdmin, StateVetOfficer, AccreditedVet, LabTechnician, StateAuditor |
| POST | `/api/premises/{id}/accredit` | Grant accredited-free standing to a MONITORED premises | StateVetOfficer |
| POST | `/api/veterinarians` | Register an accredited veterinarian | ProgramAdmin |
| POST | `/api/veterinarians/{id}/suspend` | Suspend a veterinarian's accreditation | StateVetOfficer |
| POST | `/api/entry-requirements` | Create a destination-state entry requirement matrix row | ProgramAdmin |
| PATCH | `/api/entry-requirements/{id}` | Amend a matrix row (OCC-guarded) | ProgramAdmin |
| GET | `/api/entry-requirements` | Query the destination-state entry requirement matrix | ProgramAdmin, StateVetOfficer, AccreditedVet, LabTechnician, StateAuditor |
| POST | `/api/test-records` | Register a laboratory test drawn on a premises | LabTechnician |
| POST | `/api/test-records/{id}/result` | Report a test result; POSITIVE triggers the infection cascade | LabTechnician |
| GET | `/api/premises/{id}/test-records` | List test records drawn on a premises | ProgramAdmin, StateVetOfficer, AccreditedVet, LabTechnician, StateAuditor |
| POST | `/api/certificates` | Create a DRAFT certificate of veterinary inspection; vet_id is set from X-User-ID | AccreditedVet |
| GET | `/api/certificates/{id}` | Read a certificate (materializes lazy LAPSED evaluation first) | ProgramAdmin, StateVetOfficer, AccreditedVet, LabTechnician, StateAuditor |
| GET | `/api/certificates` | List certificates with filters (traceback support) | ProgramAdmin, StateVetOfficer, AccreditedVet, LabTechnician, StateAuditor |
| POST | `/api/certificates/{id}/submit` | Submit a DRAFT certificate for state-office review; runs matrix, window, and safety validation; computes provisional fee | AccreditedVet |
| POST | `/api/certificates/{id}/issue` | Issue the certificate: mints CVI number, stamps issued_at/valid_until, computes final fee | StateVetOfficer |
| POST | `/api/certificates/{id}/reject` | Reject a certificate under review | StateVetOfficer |
| POST | `/api/certificates/{id}/revise` | Return a REJECTED certificate to DRAFT for correction (owner vet only) | AccreditedVet |
| POST | `/api/certificates/{id}/void` | Void an issued certificate; cascades to permits and movement records | StateVetOfficer |
| POST | `/api/certificates/{id}/transmit` | Electronically transmit the certificate to the destination state; appends a QUEUED TransmissionAudit (no status change) | StateVetOfficer |
| POST | `/api/movement-permits` | Request a destination-state entry permit against an ISSUED/TRANSMITTED certificate | AccreditedVet |
| GET | `/api/movement-permits/{id}` | Read a movement permit (headrooms and movement-fee totals are computed fields) | ProgramAdmin, StateVetOfficer, AccreditedVet, LabTechnician, StateAuditor |
| GET | `/api/certificates/{id}/movement-permits` | List permits attached to a certificate | ProgramAdmin, StateVetOfficer, AccreditedVet, LabTechnician, StateAuditor |
| POST | `/api/movement-permits/{id}/issue` | Issue the permit; mints the permit number | StateVetOfficer |
| PATCH | `/api/movement-permits/{id}` | Adjust allocation or window of an ISSUED permit (OCC-guarded) | StateVetOfficer |
| POST | `/api/movement-records` | Schedule a shipment under an ISSUED permit; consumes committed headroom | AccreditedVet |
| POST | `/api/movement-records/{id}/depart` | Record departure; decrements origin premises inventory | AccreditedVet |
| POST | `/api/movement-records/{id}/arrive` | Record arrival at destination (traceback) | AccreditedVet |
| POST | `/api/movement-records/{id}/cancel` | Cancel a scheduled or in-transit movement; restores inventory when cancelling from IN_TRANSIT | AccreditedVet |
| GET | `/api/movement-permits/{id}/movement-records` | List movement records under a permit (traceback) | ProgramAdmin, StateVetOfficer, AccreditedVet, LabTechnician, StateAuditor |
| POST | `/api/outbreak-zones` | Declare a disease outbreak zone (starts MONITORING) | StateVetOfficer |
| POST | `/api/outbreak-zones/{id}/escalate` | Escalate MONITORING or CONTAINED zone to ACTIVE; fires the three-link hold cascade | StateVetOfficer |
| POST | `/api/outbreak-zones/{id}/contain` | Mark an ACTIVE zone contained (holds stay in place) | StateVetOfficer |
| POST | `/api/outbreak-zones/{id}/resolve` | Resolve a MONITORING or CONTAINED zone; releases holds via the restore cascade | StateVetOfficer |
| POST | `/api/quarantine-orders` | Issue a quarantine order on a premises | StateVetOfficer |
| POST | `/api/quarantine-orders/{id}/lift` | Lift an ACTIVE quarantine order; the issuing officer may not lift their own order | StateVetOfficer |
| GET | `/api/premises/{id}/quarantine-orders` | List quarantine orders for a premises | ProgramAdmin, StateVetOfficer, AccreditedVet, LabTechnician, StateAuditor |
| GET | `/api/certificates/{id}/transmissions` | List the append-only transmission audit trail for a certificate | ProgramAdmin, StateVetOfficer, AccreditedVet, LabTechnician, StateAuditor |
| POST | `/api/transmission-audits/{id}/acknowledge` | Record destination-state acknowledgement; bubbles the certificate to TRANSMITTED | StateVetOfficer |
| POST | `/api/transmission-audits/{id}/fail` | Record a transmission failure; certificate stays ISSUED and may be re-transmitted | StateVetOfficer |

## 5. Error Code Catalogue

The catalogue below lists every error identifier and its HTTP status. Trigger conditions are defined in the narratives of §2 and §3.

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_CERTIFICATE_OWNER | 403 |
| ERR_VALIDATION | 400 |
| ERR_PREMISES_NOT_FOUND | 404 |
| ERR_VETERINARIAN_NOT_FOUND | 404 |
| ERR_ENTRY_REQUIREMENT_NOT_FOUND | 404 |
| ERR_TEST_RECORD_NOT_FOUND | 404 |
| ERR_CERTIFICATE_NOT_FOUND | 404 |
| ERR_PERMIT_NOT_FOUND | 404 |
| ERR_MOVEMENT_RECORD_NOT_FOUND | 404 |
| ERR_OUTBREAK_ZONE_NOT_FOUND | 404 |
| ERR_QUARANTINE_ORDER_NOT_FOUND | 404 |
| ERR_TRANSMISSION_AUDIT_NOT_FOUND | 404 |
| ERR_CERTIFICATE_NOT_SUBMITTABLE | 409 |
| ERR_CERTIFICATE_NOT_PENDING_REVIEW | 409 |
| ERR_CERTIFICATE_NOT_REVISABLE | 409 |
| ERR_CERTIFICATE_NOT_VOIDABLE | 409 |
| ERR_CERTIFICATE_NOT_TRANSMITTABLE | 409 |
| ERR_PERMIT_NOT_ISSUABLE | 409 |
| ERR_PERMIT_NOT_ADJUSTABLE | 409 |
| ERR_PERMIT_NOT_ISSUED | 409 |
| ERR_MOVEMENT_NOT_ADVANCEABLE | 409 |
| ERR_ZONE_INVALID_TRANSITION | 409 |
| ERR_QUARANTINE_NOT_ACTIVE | 409 |
| ERR_TRANSMISSION_NOT_ADVANCEABLE | 409 |
| ERR_TEST_RECORD_NOT_PENDING | 409 |
| ERR_PREMISES_NOT_ACCREDITABLE | 409 |
| ERR_VET_NOT_SUSPENDABLE | 409 |
| ERR_VET_NOT_CURRENT | 422 |
| ERR_PREMISES_DISEASE_HOLD | 422 |
| ERR_TEST_NOT_QUALIFYING | 422 |
| ERR_OUTBREAK_MOVEMENT_RESTRICTION | 422 |
| ERR_NO_ACTIVE_ENTRY_REQUIREMENT | 422 |
| ERR_PREMISES_SPECIES_MISMATCH | 422 |
| ERR_TEST_RECORD_MISMATCH | 422 |
| ERR_TEST_VALIDITY_EXPIRED | 422 |
| ERR_VACCINATION_WINDOW_VIOLATION | 422 |
| ERR_PERMIT_WINDOW_OUTSIDE_CVI_VALIDITY | 422 |
| ERR_MOVEMENT_OUTSIDE_PERMIT_WINDOW | 422 |
| ERR_HEAD_COUNT_EXCEEDS_INVENTORY | 422 |
| ERR_PERMIT_HEADROOM_EXCEEDED | 422 |
| ERR_ALLOCATION_BELOW_CERTIFICATE_HEADCOUNT | 422 |
| ERR_ALLOCATION_BELOW_CONSUMED | 422 |
| ERR_ZONE_WINDOW_OVERLAP | 409 |
| ERR_REQUIREMENT_WINDOW_OVERLAP | 409 |
| ERR_QUARANTINE_WINDOW_CONFLICT | 409 |
| ERR_QUARANTINE_MIN_GAP_VIOLATION | 422 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_STALE_PERMIT_VERSION | 412 |
| ERR_STALE_REQUIREMENT_VERSION | 412 |
