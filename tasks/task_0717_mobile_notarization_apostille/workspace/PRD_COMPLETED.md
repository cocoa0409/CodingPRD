# Mobile Notarization & Apostille Service API — Product Requirements Document

## 1. Introduction

Mobile and remote notarization has outgrown the paper journal. Operators now coordinate commissioned notaries and certified signing agents across multiple states, run audio-visual Remote Online Notarization (RON) sessions, verify signer credentials with scored identity checks, and route finished documents to Secretary-of-State offices for apostille or consular authentication — all while honouring per-state fee caps and multi-year record-retention mandates. This API is the system of record for that workflow. It governs the full lifecycle of a signing request, from intake and quoting, through notary assignment and the live RON session, to completion, fee reconciliation, and the immutable retention ledger.

The platform is built for four cooperating audiences: an operations team that owns intake, fee configuration, and assignment; the notaries who run sessions and keep the journal; the Secretary-of-State clerks who shepherd authentication orders; and read-only auditors. Because notarial acts carry legal weight, the system favours strict, explicit state machines and append-only records over convenience. Fees are computed twice — a provisional estimate at quote time and a reconciled final amount at completion — and every monetary figure is expressed in whole integer cents to avoid rounding drift. A server-controlled logical clock underpins commission-expiry and retention math so that the behaviour is deterministic and test-driveable.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that apply across every endpoint. The whole API is mounted under the `/notary` path prefix.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring their operational capacity. If `X-User-Role` is missing or is not one of the recognised role names, the request is rejected with `ERR_UNAUTHENTICATED`. If the header is present and valid but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognises exactly four roles: `CoordinatorOps`, `Notary`, `ApostilleClerk`, and `Viewer`.

- `CoordinatorOps` is the operations coordinator. It owns account, fee-schedule, notary, and signer setup; request intake, quoting, assignment, revision, and cancellation; journal-entry voiding; loan-package funding and cancellation; and control of the logical clock.
- `Notary` is the commissioned notary or signing agent. It schedules and runs RON sessions, records identity verifications and journal acts, starts and completes signings, and creates and scrubs loan packages.
- `ApostilleClerk` is the Secretary-of-State authentication clerk. It submits, routes, returns, resubmits, authenticates, and rejects apostille orders.
- `Viewer` is a read-only auditor that may read any resource but mutate nothing.

All four roles may invoke every read (GET) endpoint; the mutating operations are partitioned among `CoordinatorOps`, `Notary`, and `ApostilleClerk` as described above and enumerated in §4.

Role identity binds to resources as follows. When `X-User-Role` is `Notary`, `X-User-ID` is the `id` of the acting `Notary`; ownership checks on any resource that references a `Notary` compare that resource's notary foreign-key field to `X-User-ID`. When `X-User-Role` is `CoordinatorOps`, `ApostilleClerk`, or `Viewer`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may record such an identifier where a workflow calls for it but does not compare it to any entity's `id`.

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

List endpoints are paginated with two query parameters, `limit` and `offset`. The `limit` defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` defaults to 0 and represents the number of leading records to skip. List results are always sorted by `created_at` in ascending order. For every list response, the `meta` object reports `limit`, `offset`, `total_count` (the total number of matching records before pagination), and `has_more` (true when records remain beyond the current page).

### 2.4. Common Resource Properties and the Logical Clock

Every resource carries a server-minted `id` that is a UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Most resources additionally carry an `updated_at` timestamp (same format, refreshed on every mutation) and an integer `version` that starts at 1 on creation and increments by exactly one on each mutation.

Three entities are deliberately immutable and therefore carry only `id` and `created_at` — they have neither an `updated_at` field nor a `version` field. These are `FeeSchedule` (immutable fee configuration), `JournalEntry` (the append-only notarial journal), and `RetentionRecord` (the append-only retention ledger). A `JournalEntry` does have a mutable `entry_status` that may move from `COMPLETED` to `VOIDED`, but that administrative state change does not introduce a `version`; the record is otherwise never edited.

Time-dependent behaviour — commission expiry, session scheduling, retention horizons — is evaluated against a server logical clock rather than wall-clock time. The clock starts at exactly `2026-03-01T00:00:00Z` at startup; before it is ever set it reads precisely this default and never falls back to real time. A `CoordinatorOps` operator may advance or rewind it by supplying a `to_iso8601` instant.

### 2.5. Monetary Precision and the State Fee Cap

All money in this system is integer cents; there are no fractional cents because every fee input is already expressed in whole cents. The per-state `FeeSchedule` is the governing configuration for a signing: it carries the statutory `per_stamp_cents` charged per notarial act, a flat `travel_base_cents` trip fee, a `travel_per_mile_cents` mileage rate, a `ron_surcharge_cents` technology surcharge applied to remote acts, and a `state_cap_cents` ceiling. The cap is a hard limit: the total fee charged for a single signing in that state is the lesser of the computed base amount and `state_cap_cents`. Each `FeeSchedule` is keyed by a two-letter `state_code` and that code is unique among fee schedules. The `enhanced_trust_required` flag on the schedule, when true, forces signings in that state through the stricter credential-trust evaluation described in §3.

The loan-package and credential-trust calculations introduce the only fractional arithmetic in the system, and both resolve to two decimal places (or whole cents) using round-half-up. Wherever rounding is invoked below, "round half up" means a value exactly halfway between two candidates rounds to the larger magnitude.

### 2.6. State Propagation, Cascades, and Derived Fields

Mutations are immediate and consistent: when an operation changes a resource, that resource's `updated_at` is refreshed and its `version` (where present) is incremented in the same step. Several operations cascade across entities; every such secondary effect is part of the same atomic operation as its trigger and is detailed in the relevant §3 workflow. A notary's `active_session_count` is a derived field, never written directly: it always equals the number of that notary's RON sessions whose `session_status` is either `SCHEDULED` or `LIVE` (sessions in `ENDED` are excluded), and it is reconciled whenever a session's status changes and whenever the notary is read.

### 2.7. Nested Lookups and Path Validation

The entity graph is flat: peer resources reference one another by foreign-key fields rather than by nested URL ownership, and child collections (documents, sessions, verifications, journal entries, assignments, retention records) are addressed as top-level collections filtered by a parent foreign key such as `request_id`. When a path or body references a resource, existence is validated left-to-right: a missing resource anywhere in the chain yields `ERR_NOT_FOUND` before any later check runs.

### 2.8. Validation Ordering

When several checks could fail on one request, they are evaluated in a fixed priority order so that the returned error is deterministic. Authentication is checked first: an unrecognised role yields `ERR_UNAUTHENTICATED`. Authorization is second: a role not permitted for the operation yields `ERR_FORBIDDEN_ROLE`. Third, referenced-resource existence is checked left-to-right, yielding `ERR_NOT_FOUND`. Fourth, request-body well-formedness is checked — required fields present and well-typed, enum values legal, and any score within the inclusive range 0 to 100 — yielding `ERR_INVALID_REQUEST`. Fifth, on the two optimistic-concurrency-guarded operations, the supplied expected version is checked against the parent's current version, yielding `ERR_STALE_VERSION`. Sixth, the target resource's current state is checked for transition legality, yielding `ERR_INVALID_STATE`. Only after all of these pass are the domain-specific business rules of §3 evaluated. Within that business tier the relative ordering is: RON/NSA authorization first, then commission validity, then signer identity verification, then session temporal rules, then apostille duplication, then the concurrent-session cap, then credential-trust sufficiency.

### 2.9. Optimistic Concurrency Control

Two operations are guarded against stale writes. Assigning a notary to a signing request requires the request body to carry `expected_request_version`, the request `version` the client last observed. If that value does not match the request's current `version` — because another writer advanced the request (for example, a re-quote or a prior assignment) since the client read it — the assignment is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from acting on a stale fee or state snapshot. Likewise, funding a loan package requires `expected_package_version` carrying the package `version` the client last observed; if a re-scrub has advanced the package's `version` since the client read it, funding against that stale snapshot is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint accepts or requires a version field.

## 3. Business Logic & Workflows

### 3.1. Accounts, Notaries, and Signers

An operator organisation is represented by an `Account`, created with an `org_name`, a `default_state_code` for requests raised under it, and an optional `retention_years` horizon that defaults to 10 and governs how long that account's journals and records must be retained.

A `Notary` belongs to an account via `account_id` and is registered with a `full_name`, the `commission_state` that issued the commission, and a `commission_expires_at` instant. Two capability flags are recorded at registration: `ron_authorized` (whether the notary may perform Remote Online Notarization, defaulting to false) and `nsa_certified` (whether the notary is a certified Notary Signing Agent for loan signings, defaulting to false). A newly registered notary begins with `status` `ACTIVE`, an `active_session_count` of 0, and `version` 1. The commission lifecycle is its own state machine. From `ACTIVE`, an operator may move the notary to `SUSPENDED` (a reversible administrative hold) provided the notary has no RON session in `session_status` `LIVE`, otherwise `ERR_NOTARY_HAS_LIVE_SESSION`. From `SUSPENDED`, reinstatement returns the notary to `ACTIVE`, but only if `commission_expires_at` is strictly after the logical clock; a lapsed commission cannot be reinstated and yields `ERR_COMMISSION_EXPIRED`. Expiry is terminal and may be reached from either `ACTIVE` or `SUSPENDED`, moving the notary to `EXPIRED`. From `ACTIVE`, expiry additionally requires that the notary have no `LIVE` session (`ERR_NOTARY_HAS_LIVE_SESSION`); from `SUSPENDED` it has no such precondition. Expiry from either origin releases every `ACTIVE` `Assignment` held by that notary, moving each to `RELEASED`. Expiry specifically from the `ACTIVE` state cascades one level deeper: for each released assignment, if its `SigningRequest` is currently in `ASSIGNED`, the request reverts to `DRAFT` and its `assigned_notary_id` is cleared — a three-level cascade from notary to assignment to request.

A `Signer` is the principal who will sign. It belongs to an account via `account_id` and records the signer's `full_name`, `email`, and the government identification presented as `id_doc_type`, one of `DRIVERS_LICENSE`, `PASSPORT`, or `STATE_ID`.

### 3.2. Raising and Quoting a Signing Request

A `SigningRequest` is the central workflow resource and is raised by `CoordinatorOps` in `DRAFT`. At intake it captures the owning `account_id`, the `signer_id` of the principal, the `state_code` where notarization occurs (which selects the governing fee schedule), the `doc_category` (one of `GENERAL`, `REAL_ESTATE`, `LOAN_SIGNING`, or `APOSTILLE_BOUND`), and the `delivery_mode` (`RON` or `MOBILE`). It also captures the client-declared `expected_stamp_count` and an optional `estimated_travel_miles` (default 0) used only for the provisional estimate. A fresh request starts with `estimate_fee_cents` and `final_fee_cents` both at 0, and additionally carries an `actual_travel_miles` field (the reconciled mileage figure recorded at completion) that starts at 0 and remains 0 until completion writes it.

Documents are attached while the request is still in `DRAFT`. Each `RequestDocument` references its request via `request_id` and carries a `title`, a `doc_type` (one of `DEED`, `MORTGAGE`, `POA`, `AFFIDAVIT`, `BIRTH_CERT`, `DIPLOMA`, or `OTHER`), a `requires_apostille` flag (default false) marking it for Secretary-of-State authentication, and a per-document `signing_fee_cents` base fee.

Quoting moves the request from `DRAFT` to `QUOTED`. It requires that the request have at least one document, otherwise `ERR_NO_DOCUMENTS`, and that a fee schedule exist for the request's `state_code`, otherwise `ERR_FEE_SCHEDULE_MISSING`. Quoting computes the provisional fee and writes it to `estimate_fee_cents`. The estimate is built from the governing fee schedule for the request's state. Begin with the base amount: multiply the declared stamp count by `per_stamp_cents`, add the flat `travel_base_cents`, then add the mileage component, and finally — when delivery is remote — add `ron_surcharge_cents`. The mileage component is the per-mile rate `travel_per_mile_cents` multiplied by the applicable miles. For the estimate, the stamp count is `expected_stamp_count` and the miles are `estimated_travel_miles`; however, when `delivery_mode` is `RON`, the mileage is treated as 0 (a remote signing incurs no travel) even if estimated miles were supplied. The final estimate is the lesser of this base amount and the schedule's `state_cap_cents`. All arithmetic is in whole cents.

### 3.3. Verifying Signer Credentials

Before a session can begin, the signer's identity must be verified. An `IdVerification` is recorded by a notary against a request via `request_id` and a `signer_id`, supplying three sub-scores each in the inclusive range 0 to 100: a `kba_score` (knowledge-based authentication), a `credential_score` (ID-document analysis), and a `biometric_score` (liveness). Recording the verification computes three derived fields: `trust_variant`, `trust_score`, and `outcome`.

The variant is selected first. The evaluation uses the `ENHANCED` variant when either the request's `doc_category` is `LOAN_SIGNING` or the governing fee schedule for the request's state has `enhanced_trust_required` set to true; otherwise it uses the `STANDARD` variant. Under `STANDARD`, the weighted score is the KBA score times 0.5, plus the credential score times 0.3, plus the biometric score times 0.2, and the passing threshold is 70. Under `ENHANCED`, the weighted score is the KBA score times 0.3, plus the credential score times 0.4, plus the biometric score times 0.3, and the passing threshold is 75. The weighted score is rounded half up to two decimal places and stored as `trust_score`. The `outcome` is `PASS` when `trust_score` is greater than or equal to the variant's threshold, and `FAIL` otherwise. Because the two variants apply different weights and thresholds to the same three inputs, an identical set of scores can pass under `STANDARD` yet fail under `ENHANCED`.

### 3.4. Scheduling RON Sessions

A `RonSession` is scheduled by the assigned notary against an `ASSIGNED` request via `request_id`, with a `scheduled_start` and a `scheduled_end` that must be strictly after the start. The hosting notary is recorded on the session's `notary_id`, copied from the request's assignment. A session carries two independent state axes: `session_status` over `SCHEDULED`, `LIVE`, and `ENDED`; and `recording_status` over `NOT_STARTED`, `RECORDING`, and `ARCHIVED`. Audio-visual recording is mandatory for remote notarization, so the two axes are coupled at the lifecycle boundaries even though they are nominally independent. A new session begins `SCHEDULED` with recording `NOT_STARTED`.

Two temporal and capacity rules guard scheduling. The new session's half-open interval from `scheduled_start` up to but not including `scheduled_end` must not overlap any other non-`ENDED` session for the same notary, and the end must be strictly after the start; an overlap or an inverted interval yields `ERR_SESSION_OVERLAP`. Separately, the notary's `active_session_count` — the count of their `SCHEDULED` and `LIVE` sessions — must be strictly less than the concurrent-session cap of 3 before a new scheduled session is accepted; at or above the cap the request is rejected with `ERR_SESSION_CAP_EXCEEDED`.

A session may also be driven directly, by the `Notary` role, through two dedicated endpoints: `POST /notary/ron-sessions/{id}/go-live` and `POST /notary/ron-sessions/{id}/end`. Taking a scheduled session live (`go-live`) moves its `session_status` from `SCHEDULED` to `LIVE` and, as the coupled effect, advances `recording_status` from `NOT_STARTED` to `RECORDING`; the session must currently be `SCHEDULED`, otherwise `ERR_INVALID_STATE`. Going live further requires that `recording_status` be `NOT_STARTED` at that moment, otherwise `ERR_RECORDING_ALREADY_STARTED`, and that the owning request be in `ASSIGNED`, otherwise `ERR_INVALID_STATE`. Ending a live session (`end`) moves `session_status` from `LIVE` to `ENDED` and advances `recording_status` from `RECORDING` to `ARCHIVED`; the session must currently be `LIVE`, otherwise `ERR_INVALID_STATE`, and `recording_status` must currently be `RECORDING`, otherwise `ERR_RECORDING_NOT_ACTIVE`. When a request is revised or cancelled (see §3.5), the system cascades any still-`SCHEDULED` session straight to `ENDED`, archiving its recording if not already archived.

### 3.5. Assignment, Revision, and Cancellation

Assigning a notary moves a `QUOTED` request to `ASSIGNED`. This operation is optimistic-concurrency-guarded: the body must supply the target `notary_id` and `expected_request_version`, and a version mismatch is rejected with `ERR_STALE_VERSION` as described in §2.9. The target notary must be in `status` `ACTIVE`, otherwise `ERR_NOTARY_NOT_ACTIVE`, and the notary's `commission_expires_at` must be strictly after the logical clock, otherwise `ERR_COMMISSION_EXPIRED`. When the request's `delivery_mode` is `RON`, the notary must have `ron_authorized` set to true, otherwise `ERR_RON_NOT_AUTHORIZED`. When the request's `doc_category` is `LOAN_SIGNING`, the notary must have `nsa_certified` set to true, otherwise `ERR_NSA_NOT_CERTIFIED`. On success, the request's `assigned_notary_id` is set to the chosen notary and a new `Assignment` is created in `status` `ACTIVE`, linking the request and notary by `request_id` and `notary_id`.

Revision is the cyclic edge that returns an `ASSIGNED` request to `DRAFT` for rework. It is refused while any RON session for the request is `LIVE`, yielding `ERR_SESSION_LIVE`. On success it clears `assigned_notary_id`, moves the owning `Assignment` to `RELEASED`, cancels any session still in `SCHEDULED` by moving its `session_status` to `ENDED` and `recording_status` to `ARCHIVED`, and resets `estimate_fee_cents` to 0.

Cancellation is terminal and moves a request to `CANCELLED` from `DRAFT`, `QUOTED`, or `ASSIGNED`. From `DRAFT` or `QUOTED` it has no preconditions. From `ASSIGNED` it is refused while a session is `LIVE` (`ERR_SESSION_LIVE`); on success it releases the `ACTIVE` `Assignment` and cancels any `SCHEDULED` session the same way revision does.

### 3.6. Running and Completing the Signing

A notary starts the signing by moving the request from `ASSIGNED` to `IN_SESSION`. This requires exactly one RON session for the request to be in `session_status` `SCHEDULED`, otherwise `ERR_NO_SCHEDULED_SESSION`, and a `PASS` identity verification to exist for the pairing of the request and the request's signer, otherwise `ERR_ID_NOT_VERIFIED`. Because a verification with a `FAIL` outcome does not satisfy this requirement, an insufficient credential-trust result also surfaces here as `ERR_ID_NOT_VERIFIED` (the absence of any `PASS` verification — whether because none was recorded or because the recorded one failed — is reported uniformly as `ERR_ID_NOT_VERIFIED`). On success, that scheduled session is taken live: its `session_status` becomes `LIVE` and its `recording_status` becomes `RECORDING`.

During the live session the notary records each notarial act as a `JournalEntry`, which is permitted only while the request is `IN_SESSION`. Each entry references its `request_id` and the `document_id` notarized, and records an `act_type` of `ACKNOWLEDGMENT`, `JURAT`, `OATH`, or `COPY_CERTIFICATION`. The entry's `notary_id` is copied from the request's assignment, and the entry is written with `entry_status` `COMPLETED`. The journal is append-only: an entry is never edited, but an operator may administratively void one, moving its `entry_status` from `COMPLETED` to `VOIDED`.

Completing the signing moves the request from `IN_SESSION` to `COMPLETED`. It requires the request's `LIVE` session to exist, otherwise `ERR_NO_LIVE_SESSION`, and at least one `COMPLETED` journal entry for the request, otherwise `ERR_NO_JOURNAL_ENTRIES`. Completion accepts an optional `actual_travel_miles` figure and computes the reconciled final fee into `final_fee_cents`. The final fee uses the same arithmetic as the estimate and the same governing fee schedule, but with reconciled inputs: the stamp count is the number of journal entries for the request whose `entry_status` is `COMPLETED` (voided entries are excluded), and the miles are `actual_travel_miles` — again treated as 0 when `delivery_mode` is `RON`. As before, the result is the lesser of the computed base and `state_cap_cents`. Because the final inclusion set can differ from the declared figures, the final fee may diverge from the earlier estimate. Completion also ends the live session — `session_status` to `ENDED`, `recording_status` to `ARCHIVED` — and writes a `RetentionRecord`.

### 3.7. Record Retention

A `RetentionRecord` is the append-only ledger row written when a request completes. It references the completed request via `request_id`, snapshots the `journal_entry_count` (the number of `COMPLETED` journal entries at completion time), and computes a `retain_until` horizon equal to the completion instant plus the account's `retention_years`. It begins with `hold_status` `ACTIVE` and becomes `PURGEABLE` once the logical clock passes `retain_until`.

### 3.8. Secretary-of-State Apostille and Authentication

An `ApostilleOrder` routes a notarized document for Secretary-of-State authentication. It is submitted by an apostille clerk against a `document_id` (which must be a `RequestDocument` with `requires_apostille` set to true), a `destination_country`, and the `sos_office_state` the order is routed to. Submission computes two derived fields. The `authentication_type` is `APOSTILLE` when the destination is a Hague-Convention member country and `CERTIFICATION` otherwise (the embassy chain); the member set is `FR`, `DE`, `JP`, `MX`, `IT`, `ES`, `GB`, and `NL`. The flat `fee_cents` follows that branch: 2000 cents for an `APOSTILLE`, 4000 cents for a `CERTIFICATION`. A new order starts in `SUBMITTED` with `resubmit_count` 0. The system refuses a duplicate: a new order is rejected with `ERR_DUPLICATE_APOSTILLE` when an in-flight order — one in `SUBMITTED` or `ROUTED` — already exists for the same `document_id`.

The order then follows a branching lifecycle. From `SUBMITTED` a clerk may route it to `ROUTED`, but only if the referenced document's signing request is `COMPLETED`, otherwise `ERR_DOCUMENT_NOT_NOTARIZED`; alternatively, from `SUBMITTED` the clerk may reject it to the terminal `REJECTED`. From `ROUTED` the clerk may authenticate it to the terminal `AUTHENTICATED`, or the Secretary-of-State office may return it for correction, moving it to `RETURNED`. A `RETURNED` order may be resubmitted back to `SUBMITTED`, which increments `resubmit_count` by one; this cyclic resubmission is capped, and a resubmission that would push `resubmit_count` to 3 or beyond is refused with `ERR_RESUBMIT_LIMIT`.

### 3.9. NSA Loan-Signing Packages

A `LoanPackage` wraps a loan signing for a Notary Signing Agent. It is created against a request via `request_id` whose `doc_category` must be `LOAN_SIGNING` — a package raised against any other category is rejected with `ERR_NOT_LOAN_SIGNING` — and records a `lender_ref` and an optional `package_discount_pct` (default 0, expressed as a fraction such as 0.10 for ten percent). It starts in `DRAFT` with `scrub_passed` false and `package_fee_cents` 0.

Scrubbing the package moves it from `DRAFT` to `SCRUBBED`. The scrub requires the wrapped request to have at least one document whose `doc_type` is `DEED` or `MORTGAGE`, otherwise `ERR_PACKAGE_MISSING_DOC`. On success it sets `scrub_passed` to true and computes the aggregate `package_fee_cents`. That aggregation iterates over every `RequestDocument` of the wrapped request, ordered by `created_at` ascending. The rounding order is pinned: for each document, take its `signing_fee_cents`, multiply by one minus `package_discount_pct`, and round that discounted per-document amount half up to whole cents first; then sum the rounded per-document amounts. Rounding each document before summing — rather than summing then rounding once — is the contractually fixed order and can diverge from the alternative when fractional cents accumulate. A scrubbed package may be reverted to `DRAFT` for re-scrub, which sets `scrub_passed` back to false and `package_fee_cents` back to 0.

Funding moves a `SCRUBBED` package to the terminal `FUNDED`. It is optimistic-concurrency-guarded on `expected_package_version` (see §2.9) and requires the wrapped request to be `COMPLETED`, otherwise `ERR_REQUEST_NOT_COMPLETED`. A `DRAFT` package may instead be cancelled to the terminal `CANCELLED`.

## 4. Endpoint Definitions

Resource-creation endpoints return HTTP 201 with the created resource; state transitions, modifications, and reads return HTTP 200. Error responses use the status codes catalogued in §5. The table below is a summary; request bodies, response payloads, and side effects must be reconstructed from the §3 narratives.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /notary/_clock/set_current_utc | Set the server logical clock | CoordinatorOps |
| POST | /notary/fee-schedules | Create a per-state fee schedule | CoordinatorOps |
| GET | /notary/fee-schedules/{id} | Get a fee schedule | CoordinatorOps, ApostilleClerk, Notary, Viewer |
| GET | /notary/fee-schedules | List fee schedules (filter by state_code) | CoordinatorOps, ApostilleClerk, Notary, Viewer |
| POST | /notary/accounts | Create an operator account | CoordinatorOps |
| GET | /notary/accounts/{id} | Get an account | CoordinatorOps, ApostilleClerk, Notary, Viewer |
| POST | /notary/notaries | Register a notary | CoordinatorOps |
| GET | /notary/notaries/{id} | Get a notary (recomputed active_session_count) | CoordinatorOps, ApostilleClerk, Notary, Viewer |
| GET | /notary/notaries | List notaries (filter by account_id) | CoordinatorOps, ApostilleClerk, Notary, Viewer |
| POST | /notary/notaries/{id}/suspend | Suspend a notary commission | CoordinatorOps |
| POST | /notary/notaries/{id}/reinstate | Reinstate a suspended notary | CoordinatorOps |
| POST | /notary/notaries/{id}/expire | Expire a notary commission (cascades) | CoordinatorOps |
| POST | /notary/signers | Register a signer | CoordinatorOps |
| GET | /notary/signers/{id} | Get a signer | CoordinatorOps, ApostilleClerk, Notary, Viewer |
| GET | /notary/signers | List signers (filter by account_id) | CoordinatorOps, ApostilleClerk, Notary, Viewer |
| POST | /notary/requests | Create a signing request | CoordinatorOps |
| GET | /notary/requests/{id} | Get a signing request | CoordinatorOps, ApostilleClerk, Notary, Viewer |
| GET | /notary/requests | List signing requests (filter by account_id, signer_id, assigned_notary_id, status) | CoordinatorOps, ApostilleClerk, Notary, Viewer |
| POST | /notary/requests/{id}/quote | Quote the request (compute estimate) | CoordinatorOps |
| POST | /notary/requests/{id}/assign | Assign a notary (OCC-guarded) | CoordinatorOps |
| POST | /notary/requests/{id}/revise | Revert an assigned request to draft | CoordinatorOps |
| POST | /notary/requests/{id}/start-session | Start the notarization session | Notary |
| POST | /notary/requests/{id}/complete | Complete the request (compute final fee) | Notary |
| POST | /notary/requests/{id}/cancel | Cancel a request | CoordinatorOps |
| POST | /notary/documents | Add a document to a draft request | CoordinatorOps |
| GET | /notary/documents/{id} | Get a document | CoordinatorOps, ApostilleClerk, Notary, Viewer |
| GET | /notary/documents | List documents (filter by request_id) | CoordinatorOps, ApostilleClerk, Notary, Viewer |
| GET | /notary/assignments | List assignments (filter by request_id, notary_id) | CoordinatorOps, ApostilleClerk, Notary, Viewer |
| GET | /notary/assignments/{id} | Get an assignment | CoordinatorOps, ApostilleClerk, Notary, Viewer |
| POST | /notary/ron-sessions | Schedule a RON session | Notary |
| GET | /notary/ron-sessions/{id} | Get a RON session | CoordinatorOps, ApostilleClerk, Notary, Viewer |
| GET | /notary/ron-sessions | List RON sessions (filter by request_id, notary_id) | CoordinatorOps, ApostilleClerk, Notary, Viewer |
| POST | /notary/id-verifications | Record an ID/credential verification | Notary |
| GET | /notary/id-verifications/{id} | Get an ID verification | CoordinatorOps, ApostilleClerk, Notary, Viewer |
| GET | /notary/id-verifications | List ID verifications (filter by request_id, signer_id) | CoordinatorOps, ApostilleClerk, Notary, Viewer |
| POST | /notary/journal-entries | Append a notarial act | Notary |
| POST | /notary/journal-entries/{id}/void | Void a journal entry | CoordinatorOps |
| GET | /notary/journal-entries/{id} | Get a journal entry | CoordinatorOps, ApostilleClerk, Notary, Viewer |
| GET | /notary/journal-entries | List journal entries (filter by request_id, document_id, notary_id) | CoordinatorOps, ApostilleClerk, Notary, Viewer |
| POST | /notary/apostille-orders | Submit a document for authentication | ApostilleClerk |
| GET | /notary/apostille-orders/{id} | Get an apostille order | CoordinatorOps, ApostilleClerk, Notary, Viewer |
| GET | /notary/apostille-orders | List apostille orders (filter by document_id, status) | CoordinatorOps, ApostilleClerk, Notary, Viewer |
| POST | /notary/apostille-orders/{id}/route | Route to the SoS office | ApostilleClerk |
| POST | /notary/apostille-orders/{id}/reject | Reject the order | ApostilleClerk |
| POST | /notary/apostille-orders/{id}/authenticate | Mark authenticated | ApostilleClerk |
| POST | /notary/apostille-orders/{id}/return | Return the order for correction | ApostilleClerk |
| POST | /notary/apostille-orders/{id}/resubmit | Resubmit a returned order | ApostilleClerk |
| POST | /notary/loan-packages | Create an NSA loan-signing package | Notary |
| GET | /notary/loan-packages/{id} | Get a loan package | CoordinatorOps, ApostilleClerk, Notary, Viewer |
| GET | /notary/loan-packages | List loan packages (filter by request_id) | CoordinatorOps, ApostilleClerk, Notary, Viewer |
| POST | /notary/loan-packages/{id}/scrub | Scrub the package (compute package fee) | Notary |
| POST | /notary/loan-packages/{id}/unscrub | Revert a scrubbed package to draft | Notary |
| POST | /notary/loan-packages/{id}/fund | Fund the package (OCC-guarded) | CoordinatorOps |
| POST | /notary/loan-packages/{id}/cancel | Cancel a draft package | CoordinatorOps |
| GET | /notary/retention-records/{id} | Get a retention record | CoordinatorOps, ApostilleClerk, Notary, Viewer |
| GET | /notary/retention-records | List retention records (filter by request_id) | CoordinatorOps, ApostilleClerk, Notary, Viewer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN_ROLE | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_STATE | 409 |
| ERR_NO_DOCUMENTS | 409 |
| ERR_FEE_SCHEDULE_MISSING | 409 |
| ERR_NOTARY_NOT_ACTIVE | 409 |
| ERR_COMMISSION_EXPIRED | 409 |
| ERR_RON_NOT_AUTHORIZED | 409 |
| ERR_NSA_NOT_CERTIFIED | 409 |
| ERR_SESSION_LIVE | 409 |
| ERR_NO_SCHEDULED_SESSION | 409 |
| ERR_ID_NOT_VERIFIED | 409 |
| ERR_CREDENTIAL_TRUST_INSUFFICIENT | 409 |
| ERR_NO_LIVE_SESSION | 409 |
| ERR_NO_JOURNAL_ENTRIES | 409 |
| ERR_RECORDING_ALREADY_STARTED | 409 |
| ERR_RECORDING_NOT_ACTIVE | 409 |
| ERR_SESSION_OVERLAP | 409 |
| ERR_SESSION_CAP_EXCEEDED | 409 |
| ERR_NOTARY_HAS_LIVE_SESSION | 409 |
| ERR_DOCUMENT_NOT_NOTARIZED | 409 |
| ERR_DUPLICATE_APOSTILLE | 409 |
| ERR_RESUBMIT_LIMIT | 409 |
| ERR_PACKAGE_MISSING_DOC | 409 |
| ERR_REQUEST_NOT_COMPLETED | 409 |
| ERR_NOT_LOAN_SIGNING | 409 |
