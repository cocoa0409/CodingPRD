# Notary Commission & E-Notary Journal API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for a regulatory back-office platform that administers the full lifecycle of a notary public commission and the electronic recordkeeping that accompanies modern notarial practice. A state-level commissioning office uses the system to receive applications, bind surety bonds, commission and activate notaries, authorize Remote Online Notarization (RON), and police misconduct through complaints that can ultimately draw against a notary's bond. Notaries themselves use the platform to run RON sessions, verify signer credentials, notarize documents, and maintain a tamper-evident notarial journal of every act they perform — whether conducted online or in person.

The domain is, at its heart, a compliance-and-audit system layered over a workflow engine. Fees charged for notarial acts are statutorily capped, and the platform must enforce those caps under two distinct billing regimes. Time matters everywhere: session windows must not collide, bond coverage intervals must not overlap, commissions expire on a fixed term, and renewals are only honored inside a grace period. Because several of these processes mutate more than one record at once — a settled complaint, for instance, can drain a bond, exhaust it, and suspend the notary, which in turn aborts that notary's live sessions — the system places a premium on deterministic, fully-audited state transitions. Every consequential action leaves an append-only audit record so that the office can reconstruct exactly what happened and when.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request, unless explicitly exempted, must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which declares the capacity in which they are acting. The system recognizes three roles, spelled exactly as follows: `CommissionAuthority`, `Notary`, and `Anonymous`. A request that omits either header, or that presents an `X-User-Role` value outside this known set, is rejected with `ERR_UNAUTHENTICATED`. A request that is well-authenticated but attempts an operation its role is not permitted to perform is rejected with `ERR_UNAUTHORIZED`.

A small set of endpoints is exempt from authentication: creating a jurisdiction, registering a notary applicant, and the two test-driving clock endpoints do not require the headers. Notary self-registration is the only operation available to the `Anonymous` role.

When `X-User-Role` is `Notary`, `X-User-ID` is the `id` of the acting `Notary`; ownership checks on any resource that references a notary compare that resource's `notary_id` to `X-User-ID`. When `X-User-Role` is `CommissionAuthority`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, a filed complaint captures the filer's identifier in its `filed_by_user_id` field — but it does not compare it to any entity's `id`. When `X-User-Role` is `Anonymous`, `X-User-ID` is likewise an opaque identifier not tied to any persisted entity and is not compared to any record. The recorded `filed_by_user_id` is what makes segregation-of-duties enforceable on the complaint workflow described in §3.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of records returned; it defaults to 10 when omitted, may be no smaller than 1, and may be no larger than 100. The `offset` parameter is the number of records to skip from the front of the result set; it defaults to 0. Unless a specific endpoint states otherwise, list results are ordered by their `created_at` timestamp in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and Identity

Every primary resource — `Jurisdiction`, `FeeSchedule`, `Notary`, `Bond`, `Renewal`, `Session`, `Signer`, `Document`, `JournalEntry`, and `Complaint` — carries a system-managed set of fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, fixed at creation. The `updated_at` field is an ISO 8601 UTC timestamp refreshed on every mutation. The `version` field is an integer that starts at 1 and increments by one on every mutation; it underpins the optimistic concurrency mechanism in §2.7.

The `AuditEvent` record is the one exception. Audit events are an append-only trail and carry only `id` and `created_at`; they have neither an `updated_at` field nor a `version` field, because once written they are never modified. Each audit event records the `notary_id` it concerns, an `entity_type` drawn from `NOTARY`, `SESSION`, `JOURNAL_ENTRY`, `COMPLAINT`, `BOND`, or `RENEWAL`, the `entity_id` of the affected record, a machine-readable `action` label such as `SESSION_COMPLETED` or `COMPLAINT_SETTLED`, an `actor_role` of `NOTARY`, `COMMISSION_AUTHORITY`, or `SYSTEM`, and a human-readable `detail` summary.

### 2.5. Hierarchical Consistency and Cascades

Each lifecycle-bearing resource exposes a `status` field whose value is one of the exact uppercase state strings enumerated in its workflow below, and that field is the authoritative record of where the resource sits in its state machine. Several operations in this system are deliberately non-local: a single request can transition a parent and, as a consequence, several children. Whenever the server performs such a cascade, each affected record is independently mutated — its `updated_at` is refreshed and, where the entity carries one, its `version` is incremented. The server may also drive transitions that no client explicitly requested: when a notary's accumulated risk crosses the suspension threshold, or when a bond is exhausted by a settlement, the notary is suspended by the system itself rather than by an operator call. These automatic transitions are first-class and produce the same audit records and the same child cascades as their operator-initiated counterparts.

When a notary leaves active duty — through suspension, revocation, or expiry — its in-flight RON work is wound down. The precise set of sessions and documents affected, and the states they land in, is specified in the workflow narratives of §3; the principle here is simply that the system never leaves a child session "running" under a notary who can no longer preside.

### 2.6. Monetary Precision and the Fee Ledger

All monetary quantities in this system are integer counts of cents. There is no fractional currency and therefore no rounding step: every fee, cap, surcharge, bond face value, claim, and ledger total is computed and stored as a whole number of cents. Where a calculation takes a minimum of two cent values, or sums a list of them, the result is itself an exact integer number of cents.

A notary's `lifetime_fees_collected_cents` is a running ledger of fee revenue, and it is always defined as the sum of `fee_charged_cents` across that notary's journal entries that are currently in `POSTED` status. Entries that have been amended or voided are excluded. This figure is recomputed deterministically whenever the journal changes, and because it is a pure integer sum, a partial recompute always yields the same total as a full recompute.

### 2.7. Optimistic Concurrency on Renewal

The renewal workflow is guarded by optimistic concurrency control to prevent a stale renewal from silently overwriting a fresher commission term. When a renewal is submitted, the request must carry `expected_notary_version`, which is the `version` of the target `Notary` that the client last observed. The server compares this value against the notary's current `version`. If they do not match — meaning another writer has advanced the notary since the client read it — the submission is rejected with `ERR_STALE_VERSION` and HTTP status 412. A renewal legitimately supersedes the prior commission term, extending the expiry date and rebinding the bond; if an earlier renewal has already been approved and bumped the notary's `version`, a second submitter's view is stale and must not be allowed to clobber the more recent term. The `expected_notary_version` field is required on renewal submission; no other endpoint in this system takes a version field.

### 2.8. Nested Resource Resolution

Many endpoints address a resource through a path that names its parent first — a signer or document under a session, a fee schedule under a jurisdiction, a document to be notarized under its session. The server validates path identifiers left to right and rejects the request with `ERR_NOT_FOUND` at the first identifier in the path that does not resolve to an existing record. A request to notarize a document under a non-existent session, for example, fails on the session before the document is ever consulted. The same precedence applies to body-referenced resources: a foreign key that points at a missing record yields `ERR_NOT_FOUND`.

### 2.9. Validation Ordering

When several checks could fault a single request, they are evaluated in a fixed precedence so that the returned `error_id` is deterministic. Authentication is checked first: a missing or unknown-role header yields `ERR_UNAUTHENTICATED` (401). Authorization is checked next: a role not permitted for the operation yields `ERR_UNAUTHORIZED` (403). Existence is checked third: any path- or body-referenced resource that does not exist yields `ERR_NOT_FOUND` (404). Request well-formedness is checked fourth: a missing required field, a wrongly typed value, or an enum value outside its declared set yields `ERR_INVALID_REQUEST` (400); a value that is syntactically present but semantically illegal — negative cents, a commission term outside the allowed set, or an interval whose end is not after its start — yields `ERR_VALIDATION` (422). State validity is checked fifth: a resource that is not in a legal state for the requested transition yields `ERR_INVALID_STATE` (409). Only once all of these pass does the system evaluate the domain-specific business rules — segregation of duties, e-notary authorization, credential verification, grace windows, bond minimums, fee caps, time conflicts, and the renewal version check — each of which carries its own dedicated error described alongside the workflow it guards.

## 3. Business Logic & Workflows

### 3.1. Jurisdictions and the Statutory Fee Framework

Everything in this system is anchored to a `Jurisdiction`, which encodes one state's notarial rules. A `CommissionAuthority` operator creates a jurisdiction by supplying its two-letter `state_code` (uppercase, exactly two characters, and unique across all jurisdictions), a `ron_allowed` flag declaring whether Remote Online Notarization is permitted there, a `bond_minimum_cents` figure giving the smallest surety bond face value that will support a commission, a `commission_term_months` value that must be one of 48, 60, 96, or 120 months, and a `renewal_grace_days` count of days after expiry during which a notary may renew without re-applying. Two further caps live on the jurisdiction and govern RON billing: `session_act_fee_cap_cents` is an aggregate ceiling on the *sum* of per-act fees within a single session, and `ron_surcharge_cap_cents` is the most a notary may add as a technology surcharge on any one RON session. All four cent-valued jurisdiction fields must be zero or greater.

Per-act statutory maximums are kept in `FeeSchedule` rows attached to a jurisdiction. Each row names an `act_type` and a `max_act_fee_cents`, the state's ceiling for a single act of that type. The `act_type` is one of `ACKNOWLEDGMENT`, `JURAT`, `OATH`, `COPY_CERTIFICATION`, or `SIGNATURE_WITNESS`, and a jurisdiction may hold at most one schedule row per act type — the pairing of `jurisdiction_id` and `act_type` is unique. A fee schedule row records the `jurisdiction_id` it belongs to and may be reached either through its parent jurisdiction or directly by id.

### 3.2. Commissioning a Notary: Application Through Activation

A notary enters the system through self-registration, available to the `Anonymous` role. The applicant provides the `jurisdiction_id` of the commissioning state, a `full_name`, an `email` that must be unique across all notaries, and an optional `enotary_requested` flag indicating that they wish to be authorized for RON; when omitted, `enotary_requested` is `false`. A freshly registered notary begins in `APPLIED` status with `enotary_authorized` set to `false`, and its `bond_id`, `commission_starts_at`, and `commission_expires_at` all unset. The computed fields `risk_score` and `lifetime_fees_collected_cents` both begin at 0.

Before a notary can be commissioned, a surety bond must be in place. A `CommissionAuthority` operator creates a `Bond` for the notary by supplying the `notary_id`, the `jurisdiction_id`, a `face_value_cents` total coverage amount, and the bond's coverage interval as `coverage_start_at` and `coverage_end_at`. The coverage end must be strictly after the coverage start, and the face value must be zero or greater. A new bond begins in `PENDING` status; its `claims_paid_cents` and `remaining_cents` are 0 until activation. Activating a bond moves it from `PENDING` to `ACTIVE`: this requires the bond to currently be `PENDING` (otherwise `ERR_INVALID_STATE`), and it requires `face_value_cents` to be at least the commissioning jurisdiction's `bond_minimum_cents` — a shortfall is rejected with `ERR_BOND_BELOW_MINIMUM`. Activation must also clear the coverage-overlap check described in §3.3. On a successful activation the server sets `remaining_cents` equal to `face_value_cents` and `claims_paid_cents` to 0.

Commissioning advances a notary from `APPLIED` to `COMMISSIONED` and is performed by a `CommissionAuthority` operator. It requires that an `ACTIVE` bond exist for this notary whose `face_value_cents` is at least the jurisdiction's `bond_minimum_cents`, failing with `ERR_BOND_BELOW_MINIMUM` if no qualifying bond is present; and it requires the notary to be in `APPLIED` status, failing otherwise with `ERR_INVALID_STATE`. On success the server binds the notary's `bond_id` to that active bond, stamps `commission_starts_at` to the current clock instant, and computes `commission_expires_at` as the start instant plus the jurisdiction's `commission_term_months` months. Month addition is calendar-based (the day-of-month and time-of-day are preserved), clamping the day to the last valid day of the target month when the original day does not exist there. At the same moment it computes `enotary_authorized`, which becomes `true` only when the jurisdiction's `ron_allowed` is `true`, the applicant's `enotary_requested` is `true`, and the bound bond is `ACTIVE`; otherwise it remains `false`. A commissioning event is written to the audit trail. Alternatively, an `APPLIED` notary may be rejected by a `CommissionAuthority` operator, moving it to the terminal `REJECTED` status (the notary must be `APPLIED`, else `ERR_INVALID_STATE`); rejection writes an audit record and nothing more.

A `COMMISSIONED` notary is brought into service by activation, which transitions it to `ACTIVE`. Activation requires the notary to be `COMMISSIONED` (else `ERR_INVALID_STATE`) and the bound bond to be `ACTIVE` (else `ERR_BOND_NOT_ACTIVE`); it writes an audit record. `REJECTED` and `REVOKED` are the terminal states of the notary lifecycle.

### 3.3. Bond Coverage Windows and the Surety Ledger

A notary may hold a sequence of bonds over time, but two active bonds may never cover overlapping periods. When a bond is activated, the server compares its coverage interval against every *other* `ACTIVE` bond of the same notary, considered in `created_at` ascending order. Bond coverage intervals are treated as **closed** on both ends: an interval running from `coverage_start_at` to `coverage_end_at` includes both endpoints. Two closed intervals overlap when the first interval's start is at or before the second's end and the second interval's start is at or before the first's end. Crucially, touching endpoints conflict — if one bond's coverage ends at the very instant another's begins, they are considered overlapping. Any such overlap rejects the activation with `ERR_BOND_COVERAGE_OVERLAP`.

The bond also serves as the conserved pool from which substantiated complaints are paid. Its `remaining_cents` is always its `face_value_cents` less its `claims_paid_cents`, and the invariant that face value equals claims paid plus remaining holds before and after every settlement. The draw mechanics live in the complaint workflow of §3.7. A bond reaches `EXHAUSTED` when settlements have consumed its full face value, and it reaches the terminal `CANCELLED` status when its notary is revoked.

### 3.4. Running a Remote Online Notarization Session

A `Notary` opens a RON session by supplying its own `notary_id`, the session's scheduled window as `scheduled_start_at` and `scheduled_end_at`, an optional `requested_surcharge_cents` technology surcharge (defaulting to 0 and required to be zero or greater), and an optional `fee_basis` selecting the billing regime, which is either `PER_ACT` or `AGGREGATE` and defaults to `PER_ACT`. The scheduled end must be strictly after the scheduled start. At creation the session copies its `jurisdiction_id` from the presiding notary and begins in `SCHEDULED` status, with `surcharge_charged_cents`, `act_fees_total_cents`, and `session_total_fee_cents` all 0 until the session completes.

Session windows of the same notary must not collide, but the collision rule is deliberately different from the bond rule. A session's window from `scheduled_start_at` to `scheduled_end_at` is treated as **half-open**: it includes the start instant but excludes the end instant. When a session is created, its window is checked against every non-terminal session of the same notary — that is, every session whose status is `SCHEDULED`, `IDENTITY_PENDING`, `ID_VERIFIED`, `ID_FAILED`, or `ACTIVE` — considered in `created_at` ascending order; sessions in `COMPLETED`, `TERMINATED`, or `EXPIRED` are ignored. Two half-open windows overlap when the first window's start is strictly before the second's end and the second window's start is strictly before the first's end. Because the windows are half-open, adjacency is permitted: a new session whose start equals an existing session's end does *not* conflict. Any genuine overlap rejects the creation with `ERR_SESSION_TIME_CONFLICT`.

Each session needs at least one party and at least one act. A `Notary` attaches a `Signer` to a session by supplying the signer's `full_name` together with the `session_id` context, and optionally the two credential results `kba_passed` (the Knowledge-Based Authentication outcome) and `credential_analysis_passed` (the government-ID credential-analysis outcome), each defaulting to `false`. A signer begins with `id_status` of `UNVERIFIED`. A `Notary` attaches a `Document` to a session by supplying the `session_id`, the `signer_id` of the party executing it, the `act_type` being performed, and a `requested_fee_cents` the notary intends to charge before capping. A document begins in `PENDING` status with `capped_fee_cents` at 0; signers and documents may be listed within their session or reached directly by id.

### 3.5. The Identity and Notarization Flow

The presiding notary drives a session through a fixed sequence of states. Beginning the identity phase advances the session from `SCHEDULED` to `IDENTITY_PENDING`. This step requires the session to be `SCHEDULED` (else `ERR_INVALID_STATE`), the presiding notary's `enotary_authorized` to be `true` (else `ERR_ENOTARY_NOT_AUTHORIZED`), and at least one signer to be attached (else `ERR_NO_SIGNER`).

Resolving identity branches on the submitted `outcome`. When the notary resolves with a verified outcome, the session moves from `IDENTITY_PENDING` to `ID_VERIFIED`; this branch requires the session to be `IDENTITY_PENDING` (else `ERR_INVALID_STATE`) and requires *every* attached signer to have both `kba_passed` and `credential_analysis_passed` set to `true`, failing with `ERR_CREDENTIAL_NOT_VERIFIED` if any signer is missing either check. On success every signer's `id_status` becomes `VERIFIED`. When the notary resolves with a failed outcome, the session moves from `IDENTITY_PENDING` to `ID_FAILED`; this branch likewise requires the session to be `IDENTITY_PENDING` (else `ERR_INVALID_STATE`) and requires that at least one signer is still missing either `kba_passed` or `credential_analysis_passed` — if in fact every signer is already fully verified, the failed outcome is rejected with `ERR_CREDENTIAL_ALREADY_VERIFIED`. On a failed resolution, each signer that lacks either check has its `id_status` set to `FAILED`.

From `ID_VERIFIED`, starting the active notarization phase moves the session to `ACTIVE`. This requires the session to be `ID_VERIFIED` (else `ERR_INVALID_STATE`) and at least one document to be attached (else `ERR_NO_DOCUMENT`). A session that ended in `ID_FAILED` instead is wound down by termination, which moves it to the terminal `TERMINATED` status (the session must be `ID_FAILED`, else `ERR_INVALID_STATE`) and refuses every `PENDING` document on it, moving each to `REFUSED`.

Within an `ACTIVE` session, the notary works document by document. Notarizing a document moves it from `PENDING` to `NOTARIZED`; this requires the document to be `PENDING` (else `ERR_INVALID_STATE`), its parent session to be `ACTIVE` (else `ERR_INVALID_STATE`), and the document's linked signer to have an `id_status` of `VERIFIED` (else `ERR_SIGNER_NOT_VERIFIED`). The notarize request may carry an `id_method` describing how identity was established. The notary may instead refuse a document, moving it from `PENDING` to the terminal `REFUSED` status (the document must be `PENDING`, else `ERR_INVALID_STATE`). An `ACTIVE` session may also be terminated outright by its notary or by a `CommissionAuthority` operator, which moves it to `TERMINATED` (the session must be `ACTIVE`, else `ERR_INVALID_STATE`) and refuses all of its still-`PENDING` documents.

### 3.6. Completing a Session: Fee Capping and Journal Generation

Completing a session is the fiscal climax of the RON workflow, and it is permitted only from `ACTIVE`. Completion requires the session to be `ACTIVE` (else `ERR_INVALID_STATE`) and requires that at least one document in the session reached `NOTARIZED`; a session with zero notarized documents cannot be completed and is rejected with `ERR_NO_NOTARIZED_DOCUMENT`. The transition moves the session to the terminal `COMPLETED` status and, in one atomic step, stamps every fee figure, spawns the journal, and re-syncs the notary's revenue ledger.

The act-fee computation considers only the documents that reached `NOTARIZED` status in this session; documents still `PENDING` or marked `REFUSED` are excluded entirely. The notarized documents are processed in `created_at` ascending order, and the regime is selected by the session's `fee_basis`.

Under the `PER_ACT` regime, each notarized document is capped independently: its `capped_fee_cents` is the smaller of its own `requested_fee_cents` and the `max_act_fee_cents` from the fee schedule matching the session's `jurisdiction_id` and that document's `act_type`. When no fee schedule row matches that pairing, no statutory ceiling applies and the document's `capped_fee_cents` is simply its own `requested_fee_cents` (uncapped). The session's `act_fees_total_cents` is then the sum of all those per-document capped fees.

Under the `AGGREGATE` regime, the cap is applied to the whole session rather than act by act. First the raw total is formed as the sum of every notarized document's `requested_fee_cents`. The session's `act_fees_total_cents` is the smaller of that raw total and the jurisdiction's `session_act_fee_cap_cents`. The capped total is then distributed back across the documents as a waterfall, walking the notarized documents in `created_at` ascending order: a running remainder begins at the session's `act_fees_total_cents`, and for each document in turn its `capped_fee_cents` is set to the smaller of its `requested_fee_cents` and the current remainder, after which the remainder is reduced by the amount just assigned. Documents reached after the remainder is exhausted therefore receive a capped fee of 0.

Independently of the regime, the session's `surcharge_charged_cents` is set to the smaller of the session's `requested_surcharge_cents` and the jurisdiction's `ron_surcharge_cap_cents`. The session's `session_total_fee_cents` is then the sum of its `act_fees_total_cents` and its `surcharge_charged_cents`.

Completion also generates the notarial journal: the system creates exactly one `POSTED` `JournalEntry` for each `NOTARIZED` document, with that entry's `fee_charged_cents` set to the document's freshly-stamped `capped_fee_cents`. With the new entries posted, the presiding notary's `lifetime_fees_collected_cents` is recomputed as the sum of `fee_charged_cents` over all of that notary's `POSTED` journal entries, and a completion event is written to the audit trail.

### 3.7. The Notarial Journal and In-Person Acts

Not every notarial act flows through a RON session. A `Notary` may post an in-person act directly to the journal by supplying their `notary_id`, the `act_type` performed, the recorded `signer_name`, the `id_method` used to identify the signer (one of `PERSONAL_KNOWLEDGE`, `CREDIBLE_WITNESS`, `ID_CREDENTIAL`, or `KBA_PLUS_CREDENTIAL`), and the `fee_charged_cents` actually charged, which must be zero or greater. A direct entry's `session_id` and `document_id` are absent, since it derives from no session, and its `amends_entry_id` is likewise absent. A directly-created entry begins in `POSTED` status. The fee on a direct entry is policed against the statutory cap at creation: if `fee_charged_cents` exceeds the `max_act_fee_cents` from the fee schedule matching the notary's jurisdiction and that act type, the entry is rejected with `ERR_FEE_EXCEEDS_CAP`. When no fee schedule row matches that pairing, no cap is enforced and the entry is accepted regardless of `fee_charged_cents`. Posting an entry recomputes the notary's `lifetime_fees_collected_cents` and writes an audit record.

The journal is tamper-evident: posted entries are never edited in place. To correct an entry, the notary amends it. Amending moves the original entry from `POSTED` to the terminal `AMENDED` status and, in the same step, creates a brand-new `POSTED` correction entry whose `amends_entry_id` points back at the entry it supersedes, carrying the corrected `signer_name` and `fee_charged_cents` supplied on the amend request. Amendment requires the original entry to be `POSTED`, failing otherwise with `ERR_ENTRY_NOT_POSTED`, and requires the performing notary to be in either `ACTIVE` or `SUSPENDED` status (else `ERR_INVALID_STATE`). After an amendment the notary's `lifetime_fees_collected_cents` is recomputed and an audit record is written. The amend response returns the newly-created correction entry (the fresh `POSTED` record carrying the populated `amends_entry_id`) in its `data` field, with HTTP status `200 OK`. Because the superseded entry leaves `POSTED` and the correction entry enters it, the running ledger naturally reflects the corrected figure.

A `CommissionAuthority` operator may void an entry instead, moving it from `POSTED` to the terminal `VOID` status; this too requires the entry to be `POSTED` (else `ERR_ENTRY_NOT_POSTED`). Voiding recomputes the notary's `lifetime_fees_collected_cents` with the voided entry excluded and writes an audit record.

### 3.8. Complaints, Investigation, Risk, and Bond Settlement

A `CommissionAuthority` operator files a `Complaint` against a notary by naming the subject `notary_id`, a `category` of `FRAUD`, `RECORDKEEPING`, `FEE_OVERCHARGE`, or `OTHER`, and an optional `claim_amount_cents` (defaulting to 0 and required to be zero or greater) representing money sought against the notary's bond. On filing, the server captures the filer's identifier into `filed_by_user_id` from the acting `X-User-ID`, and the complaint begins in `FILED` status with `settled_claim_cents` at 0.

Opening review advances a complaint from `FILED` to `UNDER_REVIEW` and is the system's segregation-of-duties checkpoint. It requires the complaint to be `FILED` (else `ERR_INVALID_STATE`), and it requires that the operator opening review is not the subject notary — the recorded `filed_by_user_id` and the acting identifier must not coincide with the notary under investigation. A notary attempting to adjudicate a complaint against itself is rejected with `ERR_SEGREGATION_VIOLATION`. Opening review writes an audit record.

Investigation supports a revision cycle. From `UNDER_REVIEW`, the office may request additional information, moving the complaint to `INFO_REQUESTED` (the complaint must be `UNDER_REVIEW`, else `ERR_INVALID_STATE`). From `INFO_REQUESTED`, resuming review returns it to `UNDER_REVIEW` (the complaint must be `INFO_REQUESTED`, else `ERR_INVALID_STATE`) and writes an audit record; the complaint may bounce between these two states as many times as the investigation demands. From `UNDER_REVIEW` the office may also dismiss the complaint, moving it to the terminal `DISMISSED` status (the complaint must be `UNDER_REVIEW`, else `ERR_INVALID_STATE`) with an audit record.

Substantiating a complaint moves it from `UNDER_REVIEW` to `SUBSTANTIATED` (the complaint must be `UNDER_REVIEW`, else `ERR_INVALID_STATE`) and recomputes the subject notary's `risk_score`. The risk score is a weighted tally over all of that notary's complaints whose status is `SUBSTANTIATED` or `SETTLED`, taken in `created_at` ascending order; complaints that are `FILED`, `UNDER_REVIEW`, `INFO_REQUESTED`, or `DISMISSED` contribute nothing. Each contributing complaint adds a weight by category: a `FRAUD` complaint adds 40, a `FEE_OVERCHARGE` complaint adds 20, a `RECORDKEEPING` complaint adds 15, and an `OTHER` complaint adds 10. The raw sum is then capped at a ceiling of 100, so the score never exceeds 100. If, after this recomputation, the notary's `risk_score` is at least 50 and the notary is currently `ACTIVE`, the system suspends the notary automatically as a cascade of substantiation. Substantiation writes an audit record.

Settlement is the final and most consequential complaint transition, moving a complaint from `SUBSTANTIATED` to the terminal `SETTLED` status. It requires the complaint to be `SUBSTANTIATED` (else `ERR_INVALID_STATE`), the subject notary's bond to be `ACTIVE` (else `ERR_BOND_NOT_ACTIVE`), and a positive claim — a complaint whose `claim_amount_cents` is 0 cannot be settled and is rejected with `ERR_NO_CLAIM_AMOUNT`. On settlement the server draws against the bond: the draw is the smaller of the complaint's `claim_amount_cents` and the bond's current `remaining_cents`. That draw amount is recorded as the complaint's `settled_claim_cents`; it is added to the bond's `claims_paid_cents` and subtracted from the bond's `remaining_cents`, preserving the invariant that face value always equals claims paid plus remaining. Should the draw bring the bond's `remaining_cents` to exactly 0, the bond transitions to `EXHAUSTED`, and that exhaustion in turn suspends the subject notary if the notary is currently `ACTIVE` — a three-deep cascade from settlement, to bond exhaustion, to notary suspension. Settlement writes an audit record.

### 3.9. Suspension, Reinstatement, Revocation, and Expiry

Suspension can arrive two ways — by a `CommissionAuthority` operator explicitly suspending an `ACTIVE` notary, or by the system itself when a notary's `risk_score` reaches the suspension threshold of 50. Either way the notary moves from `ACTIVE` to `SUSPENDED` (the notary must be `ACTIVE`, else `ERR_INVALID_STATE`). Suspension sets `enotary_authorized` to `false` and winds down the notary's live RON work: every session of that notary in `SCHEDULED`, `IDENTITY_PENDING`, `ID_VERIFIED`, or `ACTIVE` status is cascaded to `TERMINATED`, and each such session's `PENDING` documents are cascaded to `REFUSED`. A suspension event is written to the audit trail.

A `SUSPENDED` notary may be reinstated to `ACTIVE` by a `CommissionAuthority` operator. Reinstatement requires the notary to be `SUSPENDED` (else `ERR_INVALID_STATE`), requires the `risk_score` to be below the suspension threshold of 50 — a notary still at or above that threshold cannot be reinstated and is rejected with `ERR_RISK_THRESHOLD_BLOCK` — and requires the bound bond to be `ACTIVE` (else `ERR_BOND_NOT_ACTIVE`). On reinstatement the server recomputes `enotary_authorized` and writes an audit record.

Revocation is terminal and may be triggered from either `ACTIVE` or `SUSPENDED` by a `CommissionAuthority` operator (the notary must be `ACTIVE` or `SUSPENDED` for the respective transition, else `ERR_INVALID_STATE`). Revocation sets `enotary_authorized` to `false`, cascades the notary's bond to the terminal `CANCELLED` status, and writes an audit record. When revocation is driven from `ACTIVE`, every non-terminal session of the notary is additionally cascaded to `TERMINATED` and each such session's `PENDING` documents to `REFUSED`, exactly as for suspension.

Commissions are time-limited. The platform exposes two administrative test-driving capabilities to a `CommissionAuthority` operator: one pins the logical clock to a supplied UTC instant given as `to_iso8601`, and the other advances the clock to a supplied `to_iso8601` instant and, as it does so, marks expiries. On both endpoints `to_iso8601` is required; a request that omits it or supplies a value that is not a parseable ISO 8601 instant is rejected with `ERR_INVALID_REQUEST`. Both endpoints set the logical clock to exactly the supplied instant. When the clock advances strictly past an `ACTIVE` notary's `commission_expires_at` — that is, the new clock instant is later than that timestamp — that notary transitions from `ACTIVE` to `EXPIRED`; expiry sets `enotary_authorized` to `false` and writes an audit record.

### 3.10. Renewal of a Commission

Renewals carry a commission across term boundaries. A renewal may be submitted by either a `Notary` or a `CommissionAuthority` operator, naming the `notary_id`, the `expected_notary_version` for the optimistic-concurrency guard described in §2.7, and a `new_bond_id` identifying the bond meant to cover the renewed term. A submitted renewal begins in `SUBMITTED` status. At submission the server also stamps `filed_within_grace`: the grace deadline is computed as the notary's `commission_expires_at` plus the jurisdiction's `renewal_grace_days` days, and `filed_within_grace` is `true` exactly when the current clock instant is at or before that deadline — a renewal filed at the very instant of the deadline is still within grace. Submitting a renewal increments the notary's `version` by one, which is precisely why a second, stale submission will fail the version check.

Approving a renewal is performed by a `CommissionAuthority` operator and moves the renewal from `SUBMITTED` to the terminal `APPROVED` status. Approval requires the renewal to be `SUBMITTED` (else `ERR_INVALID_STATE`), requires `filed_within_grace` to be `true` — a renewal that was filed outside the grace window cannot be approved and is rejected with `ERR_RENEWAL_OUT_OF_GRACE` even though it could still be submitted — requires the bond named by `new_bond_id` to be `ACTIVE` (else `ERR_BOND_NOT_ACTIVE`), and requires the subject notary to be in either `ACTIVE` or `EXPIRED` status (else `ERR_INVALID_STATE`). On approval the notary's `bond_id` is rebound to `new_bond_id`, the `commission_expires_at` is extended by the jurisdiction's `commission_term_months` months — computed by adding that many calendar months to the notary's existing `commission_expires_at` (or, if no expiry is yet stamped, to the current clock instant), applied uniformly whether the subject was `ACTIVE` or `EXPIRED` — and if the notary was `EXPIRED` it is restored to `ACTIVE`. A renewal event is written to the audit trail. A renewal may instead be denied by a `CommissionAuthority` operator, moving it from `SUBMITTED` to the terminal `DENIED` status (the renewal must be `SUBMITTED`, else `ERR_INVALID_STATE`) and writing an audit record.

Every resource in the system is independently retrievable and listable. The audit trail in particular may be read per notary, by individual record, or as a filtered global list, giving the commissioning office the complete recordkeeping picture the domain demands.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource — a jurisdiction, a fee schedule row, a notary, a bond, a renewal, a session, a signer, a document, a journal entry, or a complaint — return `201 Created`. Operations that drive a state transition or otherwise modify an existing resource return `200 OK`. The clock endpoints likewise return `200 OK`. Reading a resource or a list returns `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/jurisdictions` | Create a jurisdiction (state config) | CommissionAuthority |
| GET | `/jurisdictions/{jurisdictionId}` | Get a jurisdiction | CommissionAuthority, Notary |
| GET | `/jurisdictions` | List jurisdictions | CommissionAuthority, Notary |
| POST | `/jurisdictions/{jurisdictionId}/fee-schedules` | Add a per-act fee schedule row | CommissionAuthority |
| GET | `/jurisdictions/{jurisdictionId}/fee-schedules` | List fee schedules for a jurisdiction | CommissionAuthority, Notary |
| GET | `/fee-schedules/{feeScheduleId}` | Get a fee schedule row by id | CommissionAuthority, Notary |
| GET | `/fee-schedules` | List fee schedules | CommissionAuthority, Notary |
| POST | `/notaries` | Register a notary applicant | Anonymous |
| GET | `/notaries/{notaryId}` | Get a notary | CommissionAuthority, Notary |
| GET | `/notaries` | List notaries | CommissionAuthority, Notary |
| POST | `/notaries/{notaryId}/commission` | Commission an APPLIED notary | CommissionAuthority |
| POST | `/notaries/{notaryId}/reject` | Reject an APPLIED notary | CommissionAuthority |
| POST | `/notaries/{notaryId}/activate` | Activate a COMMISSIONED notary | CommissionAuthority |
| POST | `/notaries/{notaryId}/suspend` | Suspend an ACTIVE notary | CommissionAuthority |
| POST | `/notaries/{notaryId}/reinstate` | Reinstate a SUSPENDED notary | CommissionAuthority |
| POST | `/notaries/{notaryId}/revoke` | Revoke a notary | CommissionAuthority |
| GET | `/notaries/{notaryId}/audit-events` | List the audit trail for a notary | CommissionAuthority, Notary |
| GET | `/audit-events/{auditEventId}` | Get a single audit record | CommissionAuthority, Notary |
| GET | `/audit-events` | List audit records | CommissionAuthority, Notary |
| POST | `/bonds` | Create a surety bond | CommissionAuthority |
| GET | `/bonds/{bondId}` | Get a bond | CommissionAuthority, Notary |
| GET | `/bonds` | List bonds | CommissionAuthority, Notary |
| POST | `/bonds/{bondId}/activate` | Activate a PENDING bond | CommissionAuthority |
| POST | `/renewals` | Submit a commission renewal | CommissionAuthority, Notary |
| GET | `/renewals/{renewalId}` | Get a renewal | CommissionAuthority, Notary |
| GET | `/renewals` | List renewals | CommissionAuthority, Notary |
| POST | `/renewals/{renewalId}/approve` | Approve a SUBMITTED renewal | CommissionAuthority |
| POST | `/renewals/{renewalId}/deny` | Deny a SUBMITTED renewal | CommissionAuthority |
| POST | `/sessions` | Create a RON session | Notary |
| GET | `/sessions/{sessionId}` | Get a session | CommissionAuthority, Notary |
| GET | `/sessions` | List sessions | CommissionAuthority, Notary |
| POST | `/sessions/{sessionId}/signers` | Attach a signer to a session | Notary |
| GET | `/sessions/{sessionId}/signers` | List signers in a session | CommissionAuthority, Notary |
| GET | `/signers/{signerId}` | Get a signer by id | CommissionAuthority, Notary |
| GET | `/signers` | List signers | CommissionAuthority, Notary |
| POST | `/sessions/{sessionId}/documents` | Attach a document/act to a session | Notary |
| GET | `/sessions/{sessionId}/documents` | List documents in a session | CommissionAuthority, Notary |
| GET | `/documents/{documentId}` | Get a document by id | CommissionAuthority, Notary |
| GET | `/documents` | List documents | CommissionAuthority, Notary |
| POST | `/sessions/{sessionId}/begin-identity` | Move a session to IDENTITY_PENDING | Notary |
| POST | `/sessions/{sessionId}/resolve-identity` | Resolve signer identity (VERIFIED or FAILED) | Notary |
| POST | `/sessions/{sessionId}/start` | Start the active notarization phase | Notary |
| POST | `/sessions/{sessionId}/documents/{documentId}/notarize` | Notarize a document | Notary |
| POST | `/sessions/{sessionId}/documents/{documentId}/refuse` | Refuse a document | Notary |
| POST | `/sessions/{sessionId}/complete` | Complete a session | Notary |
| POST | `/sessions/{sessionId}/terminate` | Terminate a session | Notary, CommissionAuthority |
| POST | `/journal-entries` | Create an in-person journal entry | Notary |
| GET | `/journal-entries/{entryId}` | Get a journal entry | CommissionAuthority, Notary |
| GET | `/journal-entries` | List journal entries | CommissionAuthority, Notary |
| POST | `/journal-entries/{entryId}/amend` | Amend a POSTED entry | Notary |
| POST | `/journal-entries/{entryId}/void` | Void a POSTED entry | CommissionAuthority |
| POST | `/complaints` | File a complaint against a notary | CommissionAuthority |
| GET | `/complaints/{complaintId}` | Get a complaint | CommissionAuthority, Notary |
| GET | `/complaints` | List complaints | CommissionAuthority, Notary |
| POST | `/complaints/{complaintId}/open-review` | Open investigation (segregation gate) | CommissionAuthority |
| POST | `/complaints/{complaintId}/request-info` | Request additional info | CommissionAuthority |
| POST | `/complaints/{complaintId}/resume-review` | Resume review | CommissionAuthority |
| POST | `/complaints/{complaintId}/substantiate` | Substantiate a complaint | CommissionAuthority |
| POST | `/complaints/{complaintId}/dismiss` | Dismiss a complaint | CommissionAuthority |
| POST | `/complaints/{complaintId}/settle` | Settle a SUBSTANTIATED complaint | CommissionAuthority |
| POST | `/_clock/set_current_utc` | Pin the system clock to a UTC instant | CommissionAuthority |
| POST | `/_clock/advance` | Advance the clock and mark expiries | CommissionAuthority |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_SEGREGATION_VIOLATION` | 403 |
| `ERR_ENOTARY_NOT_AUTHORIZED` | 409 |
| `ERR_NO_SIGNER` | 409 |
| `ERR_NO_DOCUMENT` | 409 |
| `ERR_NO_NOTARIZED_DOCUMENT` | 409 |
| `ERR_CREDENTIAL_NOT_VERIFIED` | 409 |
| `ERR_CREDENTIAL_ALREADY_VERIFIED` | 409 |
| `ERR_SIGNER_NOT_VERIFIED` | 409 |
| `ERR_BOND_BELOW_MINIMUM` | 409 |
| `ERR_BOND_NOT_ACTIVE` | 409 |
| `ERR_FEE_EXCEEDS_CAP` | 409 |
| `ERR_RENEWAL_OUT_OF_GRACE` | 409 |
| `ERR_RISK_THRESHOLD_BLOCK` | 409 |
| `ERR_NO_CLAIM_AMOUNT` | 409 |
| `ERR_ENTRY_NOT_POSTED` | 409 |
| `ERR_SESSION_TIME_CONFLICT` | 409 |
| `ERR_BOND_COVERAGE_OVERLAP` | 409 |
| `ERR_VALIDATION` | 422 |
