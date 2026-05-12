# E-Signature API — Product Requirements Document

## 1. Introduction

Electronic signature is no longer a convenience feature; for many organizations it is the legal foundation of every commercial agreement, every employment contract, every procurement order. The platform described here is the central system of record for that activity: it manages the **templates** that organizations issue, orchestrates the **signing workflows** that bind multiple parties to a document, and produces the **evidence packages** that hold up in court if the agreement is later challenged.

Three audiences interact with the platform. **Template administrators** prepare and version the legal documents their organization will issue, configuring fillable variables and pinning signature positions on specific pages. **Contract initiators** create individual contracts from those templates, describe the chain of signers, dispatch reminders, and either complete or void the workflow. **Signers** authenticate themselves through one or more verification factors and commit signatures that are anchored by a trusted timestamp authority. Crucially, an **evidence archivist**, structurally separate from the initiator, seals the resulting evidence package — the platform enforces this segregation of duties so that the same person can never both produce and certify a contract.

The system is built around four cross-cutting commitments: every state transition is logged immutably and chained with cryptographic hashes; concurrency is resolved by first-writer-wins serialization with explicit error codes for losers; every signing event is timestamped against a trusted clock; and every quantitative claim about a contract — its progress, its evidence strength, its expiration — is recomputed deterministically from immutable inputs so that two readers always see the same number.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request, with the narrowly scoped exceptions noted in §2.3 and §3.8, must carry two headers: `X-User-ID` and `X-User-Role`. A request missing either header, or carrying a malformed value, is rejected with `ERR_UNAUTHENTICATED` and HTTP 401. A request whose role is not authorized to perform the operation is rejected with `ERR_FORBIDDEN` and HTTP 403.

Six roles exist, spelled exactly as follows: `TemplateAdmin`, `ContractInitiator`, `Signer`, `EvidenceArchivist`, `PlatformAdmin`, and `SystemSweeper`. Four of them — `TemplateAdmin`, `ContractInitiator`, `Signer`, and `EvidenceArchivist` — are entity-backed. When `X-User-Role` is one of these four, `X-User-ID` is the `id` of the acting `OrgUser`; ownership and segregation checks compare resource fields (such as the `initiator_user_id` recorded on a Contract) directly to `X-User-ID`. Each `OrgUser` carries the `legal_name` on the registered ID, the parent `org_id`, an `org_role` of `LEGAL_REP`, `AUTHORIZED_DELEGATE`, or `EMPLOYEE`, the set of authentication factors the user has registered as `registered_factors`, and a `status` of either `ACTIVE` or `SUSPENDED`. The remaining two roles — `PlatformAdmin` and `SystemSweeper` — are opaque operator identifiers not tied to any persisted entity. The server may record them on append-only `AuditLog` rows (in the `actor_user_id` and `actor_role` columns) but does not compare them to any entity's `id`.

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

All list endpoints accept two query-string parameters: `limit` and `offset`. The default `limit` is 10, the minimum is 1, and the maximum is 100; values outside this band are rejected with `ERR_VALIDATION_FAILED`. The default `offset` is 0; negative values are rejected. List endpoints sort by `created_at` ascending unless an endpoint description in §4 explicitly states a different default ordering. The `meta` object on a list response carries `limit`, `offset`, `total_count` (the total number of rows matching the query, ignoring pagination), and `has_more` (true when `offset + limit < total_count`).

### 2.4. Resource Identity, Timestamps, and Optimistic Concurrency

Every resource carries a server-minted `id` rendered as a UUID with no type prefix. Most resources also carry `created_at` and `updated_at`, both ISO 8601 UTC with three fractional digits, plus an integer `version` that starts at 1 on creation and increments by 1 on every successful mutation. A small number of entities are append-only and intentionally do not carry `updated_at` or `version`: an `IdentityVerification` is sealed at creation and only carries `id`, `created_at`, and the immutable archive marker `archived_at`; a `TimestampToken` is similarly immutable and carries only `id` and `created_at`; `ReminderEvent` is an append-only log row with `id` and `created_at`; and `AuditLog` is a hash-chained immutable record with `id` and `created_at`.

Optimistic concurrency control is mandatory on every PATCH operation that modifies a versioned resource. The client may include `version` in the request body. If the supplied `version` does not match the stored value, the server rejects the call with `ERR_VERSION_CONFLICT` and HTTP 409. If the client omits `version` from the body, the check is skipped and the write proceeds against whatever the current state is — clients use this only when they explicitly want last-writer-wins semantics. On every successful mutation, both `updated_at` and `version` advance together; reading a resource and then writing it back without re-fetching is the failure mode this mechanism is designed to catch.

### 2.5. Precision and Rounding

Two numeric quantities — `signing_progress_percent` and `evidence_strength_score` — are stored to two decimal places using half-up rounding. Half-up means that a fractional residual of exactly 0.5 at the cut point rounds up: a raw value of 73.245 rounds to 73.25, and a raw value of 73.244 rounds to 73.24. The `drift_seconds` field on a `TimestampToken` is also a numeric quantity but stores absolute clock difference and is not rounded beyond second precision. All other quantitative state — counts, version numbers, page indices — is exact integer.

### 2.6. Nested Resource Path Validation

Every URL that nests one resource inside another is validated left to right: a request against a TemplateVersion under a Template fails with `ERR_NOT_FOUND` if the Template `id` does not exist, even if the inner version `id` does. The same holds for SigningSteps under Contracts, SigningParties under SigningSteps, evidence under Contracts, and reminder events under Contracts. When the leftmost path segment validates but a deeper one does not — for example, a real Template `id` paired with a TemplateVersion `id` that belongs to a different Template — the request still fails with `ERR_NOT_FOUND`. Throughout this document and in §4, path placeholders use stable abbreviations: `{vid}` denotes a TemplateVersion `id` nested under a Template, `{sid}` denotes a SigningStep `id` nested under a Contract, and `{rid}` denotes a ReminderRule `id`.

### 2.7. Cascade and Hierarchical Consistency

Several state transitions cascade across entities. When a Contract auto-voids on expiry or is voided manually, every non-terminal SigningStep cascades to `SKIPPED`, every non-terminal SigningParty cascades to `SKIPPED`, every `ReminderRule` is disabled, and the `EvidencePackage` advances from `PENDING` to `GENERATING`. Each cascade is treated as a single logical mutation: the affected rows have their `updated_at` refreshed and their `version` incremented by 1, and a single `AuditLog` entry is appended for the originating action. When a transition refreshes a parent and a child within the same write — for example, a SigningParty advancing to `SIGNED` also pushes the parent SigningStep to `SIGNED` and may push the Contract to `COMPLETED` — every touched row receives the `updated_at` and `version` bump.

### 2.8. Audit Log Immutability and Chaining

Every state-changing operation appends one row to `AuditLog` recording `contract_id` (or `template_id` for template-scoped events), `actor_user_id`, `actor_role`, `action`, `payload_sha256` (the hex digest of the canonical JSON payload at the time of recording), `prev_log_sha256` (the `payload_sha256` of the immediately preceding `AuditLog` chained per `contract_id` or `template_id`), and `occurred_at`. The chain is per-contract for contract-scoped events and per-template for template-scoped events; the first entry in each chain has `prev_log_sha256` set to null. The action enumeration is exactly: `TEMPLATE_PUBLISHED`, `TEMPLATE_DEPRECATED`, `CONTRACT_INITIATED`, `CONTRACT_ACTIVATED`, `PARTY_SIGNED`, `PARTY_REJECTED`, `CONTRACT_VOIDED`, `CONTRACT_EXPIRED_AUTO`, `CONTRACT_REINITIATED`, `EVIDENCE_SEALED`, `EVIDENCE_EXPORTED`, and `REMINDER_FIRED`.

### 2.9. Validation Priority Order

When an endpoint is guarded by multiple validations, they are evaluated in the order of their priority — lower number first, regardless of the order they are described in the §3 narrative. The full ordering is: authentication first; then role authorization; then path-id existence; then template-publication state; then Contract state; then SigningParty active-state; then segregation-of-duties for activation; then segregation-of-duties for sealing; then identity-verification freshness and factor coverage; then delegation validity; then contract expiration; then timestamp-hash matching; then timestamp drift; then reminder-event idempotency uniqueness; then optimistic-concurrency `version` check; then workflow-locked structural-edit check; then template permission scope; then legal-representative MFA minimum; then notary-reference requirement; then re-initiation eligibility. A failure at an earlier step short-circuits and prevents later checks from firing — so an unauthenticated caller hitting the sign endpoint receives `ERR_UNAUTHENTICATED`, never `ERR_PARTY_NOT_ACTIVE`, even if the party is also in the wrong state.

### 2.10. Concurrency Resolution

Concurrent writes against the same resource are serialized first-writer-wins on the resource's status (or version, where applicable). Two simultaneous sign attempts against the same `signing_party_id` resolve to exactly one winner; the loser sees a party that is no longer in `AUTHENTICATING` and is rejected with `ERR_INVALID_STATE` and HTTP 409. The same outcome holds when sign races decline against the same party, or when two void writers — for example, the initiator's manual void racing the auto-void produced by the periodic sweep — target the same Contract: exactly one writes, the other receives `ERR_INVALID_STATE`, and the surviving `void_reason` reflects whichever path won. When two reminder firings under the same `reminder_rule_id` arrive with the same `idempotency_key` simultaneously, only one `ReminderEvent` row is created; the duplicate is rejected with `ERR_DUPLICATE_REMINDER`. When a PATCH against a DRAFT TemplateVersion races another PATCH on the same row, the OCC `version` check resolves it: exactly one writer commits, the stale writer receives `ERR_VERSION_CONFLICT`. When seal and export of the same `EvidencePackage` arrive concurrently, export only succeeds if seal has already committed; otherwise the export call sees a non-`SEALED` state and is rejected with `ERR_INVALID_STATE`.

## 3. Business Logic & Workflows

### 3.1. Template Authorship and Versioning

A `TemplateAdmin` introduces a new agreement type into the platform by creating a `Template` carrying a `name` (1 to 120 characters; unique within the same `owner_org_id`), a `category` chosen from `HR`, `SALES`, `PROCUREMENT`, `LEGAL`, `FINANCE`, or `OTHER`, the `owner_org_id` of the issuing organization, and an optional `permission_scope` defaulting to `ORG_ONLY` and otherwise drawn from `CROSS_ORG` or `PUBLIC`. The newly minted Template starts with `status = ACTIVE` (the alternative is `ARCHIVED`), a `latest_version_number` of 0, and a null `published_version_number` — it has been declared but no document has been uploaded yet. Mutable fields (`name`, `category`, `permission_scope`) can be edited later under OCC.

A document is uploaded against a Template by creating a new `TemplateVersion`. The upload payload provides the `document_blob_sha256` (exactly 64 lowercase hex characters), the `page_count` (which must be at least 1), the `variable_fields` array describing fillable placeholders by `{name, type, required}`, and the `signature_positions` array — a list of rectangles `{role_key, page, x, y, w, h, kind}` where `kind` is one of `NORMAL` or `SEAM`. A `SEAM` position spans the boundary between two consecutive pages and is the structural anchor for cross-page seam signatures. Each new version receives a `version_number` that monotonically increases per Template starting at 1, and the parent Template's `latest_version_number` is updated to match. The new version starts as `DRAFT`. While in `DRAFT` it can be edited freely (under OCC) to revise `document_blob_sha256`, `page_count`, `variable_fields`, or `signature_positions` — the `version` field guards these PATCH calls and a stale `version` is rejected with `ERR_VERSION_CONFLICT`.

Publishing a TemplateVersion advances it from `DRAFT` to `PUBLISHED` and requires that the version currently be `DRAFT` and that at least one signature position have been pinned. On success, the parent Template's `published_version_number` is set to the version's `version_number` and an `AuditLog` row with action `TEMPLATE_PUBLISHED` is appended. The publishing user is recorded — and is later compared against the activator of any Contract built on this version, to enforce segregation of duties (see §3.3). A `PUBLISHED` version may later be advanced to `DEPRECATED`, but only if no Contract that references it is currently in `DRAFT`, `PENDING_SIGN`, or `PARTIALLY_SIGNED`. A successful deprecate appends `TEMPLATE_DEPRECATED`, and if the Template's `published_version_number` equalled the deprecated version's `version_number`, the parent's `published_version_number` is cleared back to null.

### 3.2. Contract Composition in DRAFT

A `ContractInitiator` creates a `Contract` against a `PUBLISHED` TemplateVersion by submitting a payload containing the `template_version_id`, a `title` (1 to 200 characters), the `variable_values` (a key-value map matching the template's `variable_fields`), an `expires_at` deadline, and optionally a `reinitiated_from_contract_id`. On creation the Contract receives a fresh `id`, the `initiator_user_id` and `initiator_org_id` copied from the authenticated request, and `status = DRAFT`. The fields `activated_at`, `completed_at`, `voided_at`, `void_reason`, and `document_fingerprint_sha256` all default to null at creation.

Permission to instantiate is governed by the parent Template's `permission_scope`. A `PUBLIC` template may be instantiated by any organization. A `CROSS_ORG` template may be instantiated by any active organization. An `ORG_ONLY` template may only be instantiated when the initiator's `initiator_org_id` matches the template's `owner_org_id`. Violations are rejected with `ERR_TEMPLATE_PERMISSION_DENIED`. If the referenced TemplateVersion is not in `PUBLISHED`, the call is rejected with `ERR_TEMPLATE_NOT_PUBLISHED`.

While the Contract sits in `DRAFT`, the initiator composes its workflow. Signing steps are appended one at a time: each `SigningStep` carries a `step_index` starting at 1 and strictly increasing per Contract (the pair `(contract_id, step_index)` is unique), a `mode` of either `SEQUENTIAL` or `PARALLEL_COUNTERSIGN`, and an optional `branch_condition` of the form `{variable, operator, value, on_false_skip}`. Within each step, parties are added one by one: each `SigningParty` carries the `signing_step_id` of its parent step, the `contract_id` denormalized from that step, a `role_key` (a stable identifier such as `PARTY_A` or `WITNESS_1` aligned with the template's signature positions), a `signer_type` of `INDIVIDUAL`, `ORG_LEGAL_REP`, or `ORG_DELEGATE`, the `signer_user_id` of the actual signer, an optional `signer_org_id`, an optional `delegation_authorization_id`, and `required_auth_factors` — a non-empty subset of `SMS`, `FACE`, `CA_CERT`, and `BANK_CARD` of length 1 to 4 with no duplicates. When `signer_type` is `ORG_LEGAL_REP` or `ORG_DELEGATE`, `signer_org_id` is required; for `INDIVIDUAL` signers it is null. When `signer_type` is `ORG_DELEGATE`, the `delegation_authorization_id` must be non-null and must point to an active `OrgUser` whose `org_role` is `AUTHORIZED_DELEGATE` within `signer_org_id`; otherwise the call is rejected with `ERR_DELEGATION_INVALID`.

Two safety constraints apply at composition. A signing party representing an `ORG_LEGAL_REP` must require multi-factor authentication: its `required_auth_factors` array must have length of at least 2, otherwise the platform rejects the call with `ERR_LEGAL_REP_REQUIRES_MFA`. And every structural edit to a Contract — modifying `title`, `expires_at`, `variable_values`, or appending signing steps or parties — is permitted only while the Contract is in `DRAFT`. Once the Contract has left `DRAFT`, any such structural edit is rejected with `ERR_WORKFLOW_LOCKED`. While `DRAFT` mutations are allowed, the OCC `version` field still applies to every PATCH against the Contract.

### 3.3. Activation and the Document Fingerprint

Activation is the moment at which the Contract leaves `DRAFT` and becomes binding. The initiator triggers it once the workflow is fully described. The activation is rejected unless the Contract is currently in `DRAFT`, the referenced TemplateVersion is in `PUBLISHED`, at least one SigningStep with `step_index = 1` exists, every SigningStep has at least one SigningParty, every required entry in `variable_values` is present and matches the TemplateVersion's `variable_fields`, the activating user is not the same `OrgUser` who published the referenced TemplateVersion (segregation of duties — violation yields `ERR_SEGREGATION_OF_DUTIES`), and the current server time is strictly less than the Contract's `expires_at` (an expired contract at activation time is rejected with `ERR_CONTRACT_EXPIRED`). If the Contract is not in `DRAFT`, the call returns `ERR_INVALID_STATE`.

On a successful activation, four things happen in one logical write. First, `Contract.status` advances `DRAFT → PENDING_SIGN` and `Contract.activated_at` is set to the current server time. Second, the `document_fingerprint_sha256` is computed and pinned for the rest of the Contract's lifecycle — the fingerprint is built deterministically from the TemplateVersion and `variable_values`, in two strict steps. In step one, for each page index from 1 through `page_count` ascending, the system constructs a UTF-8 canonical JSON object containing the `page_index`, the TemplateVersion's `document_blob_sha256` as `blob_sha256`, and the subset of `variable_values` whose keys' associated `signature_positions` have a `page` equal to that index, sorted by key ascending; that JSON is hashed with SHA-256 to yield a per-page hex digest. In step two, the per-page hex digests are concatenated in ascending page order as ASCII bytes with no separator between them, and the concatenated bytes are themselves hashed with SHA-256 to yield the final hex digest stored as `document_fingerprint_sha256`. The order is fixed: per-page hashing first, then concatenation, then a final hash — the alternative order (hashing concatenated variable bodies before per-page digestion) yields a different fingerprint and is forbidden. Third, the SigningStep with `step_index = 1` advances `PENDING → ACTIVE`, which in turn drives its child SigningParty rows from `WAITING` into `AUTHENTICATING` (see §3.4 for how that fan-out works). Fourth, an `AuditLog` row with action `CONTRACT_ACTIVATED` is appended, refreshing the chain.

### 3.4. Step Activation, Branch Conditions, and Party Authentication

A SigningStep activates only when every step with a lower `step_index` is in a terminal state, the parent Contract is in `PENDING_SIGN` or `PARTIALLY_SIGNED`, and either the step has no `branch_condition` or the branch condition evaluates true against `variable_values`. On activation the step's `activated_at` is stamped with the current server time and the step's `mode` decides how its parties move forward. In `PARALLEL_COUNTERSIGN` mode every child SigningParty flips from `WAITING` to `AUTHENTICATING` simultaneously. In `SEQUENTIAL` mode only the first party (the lowest-ordered one in the step) flips to `AUTHENTICATING`; subsequent parties advance only after the previous one reaches a terminal status of `SIGNED` or `SKIPPED`.

When a step has a `branch_condition` and the condition evaluates false, the step is auto-skipped — its `status` flips directly from `PENDING` to `SKIPPED`, every child SigningParty cascades from `WAITING` to `SKIPPED`, and the next eligible step (the one with the lowest `step_index` still in `PENDING`) is then evaluated for activation, either advancing to `ACTIVE` or skipping in the same way.

A party in `AUTHENTICATING` is the one waiting for the human signer to act. Two outcomes are possible: signing, or declining.

### 3.5. Identity Verification and the Sign Act

Before a `Signer` may commit, they must establish identity. An `IdentityVerification` is an append-only record carrying the `subject_user_id` being verified, optionally the `contract_id` it serves, a nullable `signing_party_id` that becomes set when the verification is consumed, the `factors_attempted` array of `{factor, outcome}` pairs where outcome is `PASS` or `FAIL`, the computed `factors_passed` (deduplicated subset of attempted where outcome was `PASS`), the computed `real_name_match` boolean indicating whether the legal name on the verified ID matches the subject's registered `legal_name` on `OrgUser`, the computed `org_binding_verified` boolean (true only when `signer_type` is `ORG_LEGAL_REP` or `ORG_DELEGATE` and the organizational tie has been confirmed; default false), the computed `identity_strength` band (`WEAK`, `STRONG`, or `EXTRA_STRONG`), and the final `result` of `VERIFIED` or `FAILED`. On creation, `archived_at` is stamped to mark the immutable archive position.

The identity strength band is decided as follows. If no factor has passed, the verification is `FAILED` and the strength is `WEAK`. If exactly one factor has passed, the strength is `WEAK`, and the result is `VERIFIED` only if `real_name_match` is true (otherwise `FAILED`). If at least two factors have passed but `CA_CERT` is not among them, the strength is `STRONG` and the result is `VERIFIED` only if `real_name_match` is true. If at least two factors have passed and both `CA_CERT` and `BANK_CARD` are among them, the strength is `EXTRA_STRONG` and the result is `VERIFIED` only if `real_name_match` is true. If at least two factors have passed and `CA_CERT` is among them but `BANK_CARD` is not, the strength is `STRONG` and the result is `VERIFIED` only if `real_name_match` is true.

When the signer is ready, they commit a signature by submitting a payload containing the `tsa_anchor_at` value supplied by the trusted timestamp authority, the `tsa_provider` identifier, the opaque `tsa_token_value`, and the `identity_verification_id` of the verification they produced for this sign. The system enforces a sequence of checks. The party must currently be in `AUTHENTICATING`, otherwise the call is rejected with `ERR_PARTY_NOT_ACTIVE`. The Contract must be in `PENDING_SIGN` or `PARTIALLY_SIGNED`, otherwise the call is rejected with `ERR_INVALID_STATE`. The acting `X-User-ID` must equal the party's `signer_user_id` — except that an `ORG_LEGAL_REP` may sign on behalf of an `ORG_DELEGATE` under the registered `delegation_authorization_id`. The current server time must be strictly less than the Contract's `expires_at`; if not, the call is rejected with `ERR_CONTRACT_EXPIRED`. There must exist a fresh `IdentityVerification` for `(subject_user_id = signer_user_id, contract_id = Contract.id, signing_party_id = null)` with `result = VERIFIED`, archived within the last `AUTH_TTL_MINUTES` minutes (the operational freshness window), and whose `factors_passed` is a superset of the party's `required_auth_factors`; otherwise the call is rejected with `ERR_AUTH_FACTORS_INSUFFICIENT`.

On a successful sign, a new `TimestampToken` row is created carrying the Contract `id`, the `signing_party_id`, `server_anchor_at` set to the current server time, `tsa_anchor_at` from the request body, the `tsa_provider` and `tsa_token_value` from the request body, and a `hash_signed` set to the Contract's pinned `document_fingerprint_sha256`. The `drift_seconds` column is computed as the absolute difference in seconds between `tsa_anchor_at` and `server_anchor_at`. If `hash_signed` does not equal `document_fingerprint_sha256` at the moment of issue, the sign is rejected with `ERR_TIMESTAMP_HASH_MISMATCH`. If `drift_seconds` exceeds the operational ceiling of 60 seconds (`MAX_TSA_DRIFT_SECONDS`), the token's `verification_status` is set to `INVALID` and the sign is rejected with `ERR_TIMESTAMP_DRIFT_EXCEEDED`; otherwise the token's `verification_status` is `VALID`. The party then transitions `AUTHENTICATING → SIGNED`, its `signed_at` is stamped to the current server time, its `timestamp_token_id` is set to the new token's id, its `identity_verification_id` is set to the consumed verification's id (and that verification's `signing_party_id` is set in the same write so it can never be re-consumed by another party). Every `ReminderRule.misses_count` under this Contract is reset to 0, and an `AuditLog` row with action `PARTY_SIGNED` is appended.

The four checks above are evaluated in priority order — authentication first, then role authorization, then path-id existence, then state checks (Contract state, then party state), then segregation-of-duties checks, then identity-factor freshness, then delegation, then expiration, then timestamp-hash matching, then drift. Earlier failures short-circuit later ones (see §2.9 for the full ordering).

### 3.6. Step Completion, Contract Completion, and Decline

A SigningStep advances `ACTIVE → SIGNED` automatically when every party under it has reached `SIGNED` or `SKIPPED`. The step's `completed_at` is stamped, and the next step (the lowest `step_index` still in `PENDING`) is then evaluated for activation — either advancing to `ACTIVE` if its branch condition holds (or it has no branch condition), or skipping if its branch condition is false. The cascade unwinds step by step until either a step is activated or every remaining step is skipped.

When the last party of the last required step signs, the Contract transitions from `PARTIALLY_SIGNED` to `COMPLETED` (or directly from `PENDING_SIGN` to `COMPLETED` if the workflow had only one party). The transition fires only when every SigningParty across every SigningStep is in `SIGNED` or `SKIPPED` and every SigningStep with an evaluated `branch_condition` is in `SIGNED` or `SKIPPED`. The Contract's `completed_at` is stamped to the current server time, `signing_progress_percent` is finalized at 100.00, `evidence_strength_score` and `evidence_tier` are recomputed (per §3.10), and the `EvidencePackage` cascades from `PENDING` to `GENERATING`. The first party-signed event under a multi-party Contract (i.e., when at least one party is `SIGNED` and at least one party is still in a non-terminal status that is not `SKIPPED`) advances the Contract from `PENDING_SIGN` to `PARTIALLY_SIGNED` and recomputes both `signing_progress_percent` and `evidence_strength_score`. Subsequent party-signed events under an already-partially-signed Contract keep the status at `PARTIALLY_SIGNED` and re-trigger the same recomputation.

Declining is the antagonistic outcome. A party in `AUTHENTICATING` can be declined by the signer; the call requires the same identity check as sign (the acting `X-User-ID` must match the party's `signer_user_id` or an authorized delegate) and that the party is currently in `AUTHENTICATING`. On decline the party advances `AUTHENTICATING → DECLINED`. The parent SigningStep cascades to `REJECTED` (its `completed_at` is stamped, all sibling parties under that step cascade to `SKIPPED`), and the Contract cascades to `VOIDED` with `void_reason = REJECTED_BY_PARTY`. An `AuditLog` row with action `PARTY_REJECTED` is appended. As described in §2.7, when the Contract voids it disables all of its `ReminderRule` rows, cascades any non-terminal SigningSteps and SigningParties to `SKIPPED`, and pushes its `EvidencePackage` from `PENDING` to `GENERATING`.

### 3.7. Manual Void, Auto-Void, and Re-Initiation

The `ContractInitiator` may manually void their Contract, but only while the Contract is in `PENDING_SIGN` and no SigningParty has reached `SIGNED` yet. On a successful manual void, the Contract status flips to `VOIDED`, `voided_at` is stamped to the current server time, and `void_reason` is set to `MANUAL`. The full cascade described in §2.7 applies, and an `AuditLog` row with action `CONTRACT_VOIDED` is appended. If the Contract is already past the gate — for example, it has a signed party, or it is `PARTIALLY_SIGNED` — the manual void is rejected with `ERR_INVALID_STATE`.

Auto-void happens during the periodic sweep. Every Contract whose `status` is in `PENDING_SIGN` or `PARTIALLY_SIGNED` and whose `expires_at` is on or before the current server time is auto-voided with `void_reason = EXPIRED_AUTO`, the same cascade fires, and an `AuditLog` row with action `CONTRACT_EXPIRED_AUTO` is appended. The boundary is inclusive: the moment-on-the-line counts as expired (the test for activation and signing uses strict less-than expiration, and the test for sweep auto-void uses on-or-after — together these guarantee that no signing call can race past an expiration boundary).

A previously voided or expired Contract may be re-initiated. The new Contract carries `reinitiated_from_contract_id` pointing back to the source Contract's `id`. The source must be in either `VOIDED` or `EXPIRED` status, it must belong to the same `initiator_org_id` as the new Contract, and there must not already be a successful re-initiation pointing to that source — only one chain may extend from any given voided source. Violations of any of these conditions are rejected with `ERR_REINITIATE_INVALID`. A successful re-initiation appends a `CONTRACT_REINITIATED` `AuditLog` entry on the new Contract's chain.

### 3.8. Reminders and the Sweep

A `ReminderRule` is created on a Contract with an `interval_hours` (between 1 and 168 inclusive — i.e., an hourly cadence up to a weekly cadence), a non-empty `channels` array drawn from `SMS`, `EMAIL`, and `IM` with no duplicates, an `escalation_after_misses` count between 0 and 10 inclusive, and an optional `enabled` boolean defaulting to true. The rule additionally tracks `last_fired_at` (server time of the most recent reminder firing) and `misses_count` (number of reminders fired since the last party signed; reset to 0 on any party reaching `SIGNED`). The rule may be edited under OCC; the OCC `version` check applies on every PATCH.

The sweep evaluates every enabled `ReminderRule` under a Contract in `PENDING_SIGN` or `PARTIALLY_SIGNED`. For each such rule, the system computes a reference time — the rule's `last_fired_at` if it has fired before, or the Contract's `activated_at` otherwise — and a threshold time equal to the reference time plus `interval_hours` multiplied by 3600 seconds. A reminder is due when the current server time is at or after the threshold time (boundary inclusive). When a reminder is due, the rule's `misses_count` is incremented by 1; the rule escalates only when the new `misses_count` is strictly greater than `escalation_after_misses` (the configured count itself does not trigger escalation; one more miss than configured does). When a reminder fires, a `ReminderEvent` row is created with the `reminder_rule_id`, the denormalized `contract_id`, the `fired_at` set to the current server time, the `channels_used` array (the rule's `channels`, plus the additional `INITIATOR_IM` channel if escalation applies), the boolean `escalated`, and an `idempotency_key` of the form `{reminder_rule_id}:{slot}` where `slot` is the integer floor of the current server time divided by `interval_hours * 3600` seconds. The pair `(reminder_rule_id, idempotency_key)` is unique — duplicate firings of the same slot are rejected with `ERR_DUPLICATE_REMINDER`. The rule's `last_fired_at` is then set to the current server time, and `misses_count` is set to the incremented value. A `REMINDER_FIRED` `AuditLog` entry is appended.

When a SigningParty reaches `SIGNED`, every `ReminderRule.misses_count` under the Contract is reset to 0 — see §3.5. When the Contract voids (manually, by expiry, or by decline), every `ReminderRule.enabled` under it is set to false.

Two test-driving capabilities exist alongside the operational sweep. An admin-only clock-advance capability advances the logical clock to a supplied `to` instant. The clock only moves forward — a `to` value earlier than the current logical clock is rejected; a `to` value equal to the current logical clock is idempotent. A sweep-run capability runs the periodic sweep on demand, returning a small object indicating how many contracts auto-voided and how many reminders fired in this run. The sweep-run capability is the only endpoint that may be invoked by `SystemSweeper` (in addition to `PlatformAdmin`); when invoked by `SystemSweeper`, the `X-User-ID` header is opaque and not validated against any persisted entity.

### 3.9. Signing Progress: Two Variants

The Contract's `signing_progress_percent` is the chronological measure of how much of the workflow has actually been completed. Conceptually, it counts every SigningParty whose parent SigningStep is in `ACTIVE`, `SIGNED`, or `REJECTED` — these are the parties whose steps have actually been engaged. Steps in `PENDING` are excluded because they have not been activated yet, and steps in `SKIPPED` are excluded because their branch condition evaluated false and the parties under them were never required. Each included party contributes a uniform weight of 1 (`WEIGHT_PER_PARTY`). The numerator is the count of included parties whose `status` equals `SIGNED`, ordered by `signed_at` ascending; the denominator is the total weight over the included parties; the percentage is 100 multiplied by numerator divided by denominator, rounded half-up to two decimal places. When the denominator is 0 (no eligible parties yet), the percentage is `0.00`.

The progress endpoint accepts an optional `variant` query parameter. The default — chronological — is the value stored on the Contract row. The alternative, `forward_looking`, asks a different question: how much of the still-possible workflow has been signed. The forward-looking variant assumes every PENDING SigningStep will activate and every WAITING SigningParty in those steps will be required, so it includes every party under every non-`SKIPPED` step (`PENDING` plus `ACTIVE` plus `SIGNED` plus `REJECTED`) in the denominator; the numerator is still the count of `SIGNED` parties. For identical inputs, the forward-looking variant yields a smaller percentage than the chronological one whenever there exists at least one PENDING step containing at least one not-yet-signed party — and it differs from the chronological variant whenever any step is in `PENDING` and at least one party has `SIGNED`. The endpoint returns an object with `progress_percent`, `variant`, and a `breakdown` array.

### 3.10. Evidence Strength: Continuous Score and Tier Banding

Every Contract carries `evidence_strength_score` (a number from 0 to 100, two decimal places, half-up rounding) and `evidence_tier` (one of `BRONZE`, `SILVER`, `GOLD`, or `NOTARIZED`). Both are recomputed on every `AUTHENTICATING → SIGNED` party transition, on Contract auto-void, and again when the `EvidencePackage` is sealed.

The score is built from four weighted inputs.

The first input is the **identity score**, weighted at 0.30 (`W_IDENTITY`). It is the average over every party currently in `SIGNED` of an identity tier value: 50 if the party's `factors_passed` count is 1; 70 if `factors_passed` count is at least 2 (multi-factor); 90 if `factors_passed` includes `CA_CERT`; and 100 if `factors_passed` includes both `CA_CERT` and `BANK_CARD`. When no party has signed yet, the identity score is 0.

The second input is the **timestamp score**, weighted at 0.30 (`W_TIMESTAMP`). It is the average over every signed party of a timestamp tier: 100 if the party's `TimestampToken.verification_status` is `VALID` and its `drift_seconds` is at most 5 (`DRIFT_TIGHT_SECONDS`); 60 if `verification_status` is `VALID` and `drift_seconds` is greater than 5 but at most 30 (`DRIFT_LOOSE_SECONDS`); 0 in every other case. When no party has signed, the timestamp score is 0.

The third input is the **hash score**, weighted at 0.20 (`W_HASH`). It is 100 when the Contract's pinned `document_fingerprint_sha256` matches a recomputation of the canonical hash from the TemplateVersion and `variable_values` at completion time, and 0 otherwise. While the Contract has not yet completed, the hash score defaults to 100.

The fourth input is the **notary score**, weighted at 0.20 (`W_NOTARY`). It is 0 when the EvidencePackage's `notary_provider` is `NONE`, 60 when it is `NOTARY_PUBLIC`, and 90 when it is `BLOCKCHAIN`.

The pre-tier raw score is computed as 0.30 multiplied by the identity score, plus 0.30 multiplied by the timestamp score, plus 0.20 multiplied by the hash score, plus 0.20 multiplied by the notary score, then rounded half-up to two decimal places. The tier is then assigned by banding the raw score: `BRONZE` when the raw score is strictly less than 40 (`TIER_SILVER_MIN`); `SILVER` when the raw score is at least 40 and strictly less than 70 (`TIER_GOLD_MIN`); `GOLD` when the raw score is at least 70 and strictly less than 90 (`TIER_NOTARIZED_MIN`); and `NOTARIZED` when the raw score is at least 90 and `notary_provider` is not `NONE` (the `NOTARIZED` band requires a notary commitment in addition to the score threshold).

When and only when the tier resolves to `NOTARIZED`, the score is re-evaluated in a second pass with the notary score replaced by the smaller of 100 and the notary score plus 10 (`NOTARIZED_BONUS`). The final score uses this adjusted notary score; the tier is decided on the first pass and is not re-banded after the bonus — so the bonus can lift the displayed score above 90 but cannot promote a `GOLD` Contract into `NOTARIZED`.

A pre-seal preview is available before the EvidencePackage is sealed. The preview reports a provisional score and a provisional tier computed with the notary score forced to 0 — even when `notary_provider` is configured, no notary commitment has been made yet, so the score may not yet credit it. For identical inputs at the post-completion-but-pre-seal moment, the provisional score is strictly less than the post-seal score whenever `notary_provider` is not `NONE`, and equal to the post-seal score when `notary_provider` is already `NONE`. The endpoint returns an object with `provisional_score` and `provisional_tier`.

### 3.11. Evidence Sealing and Judicial Export

Every Contract that reaches `COMPLETED` or `VOIDED` cascades its `EvidencePackage` from `PENDING` to `GENERATING`. The package is one-per-Contract and carries a `notary_provider` (defaulting to `NONE`, otherwise `NOTARY_PUBLIC` or `BLOCKCHAIN`), an optional `notary_reference` (an external reference id — a notary case number or a blockchain transaction hash), `package_sha256` (set at sealing), `sealed_at`, and `exported_at`.

Sealing is performed by an `EvidenceArchivist` and requires that the package be in `GENERATING`, that the acting user is not the same `OrgUser` as the Contract's `initiator_user_id` (segregation of duties — violation yields `ERR_SEGREGATION_OF_DUTIES`), and that if `notary_provider` is anything other than `NONE`, then `notary_reference` is non-empty (otherwise the call is rejected with `ERR_NOTARY_REFERENCE_REQUIRED`). On a successful seal, `package_sha256` is computed as a hex digest over the canonical evidence bundle — the Contract's `document_fingerprint_sha256`, every `TimestampToken` row attached to the Contract, every `IdentityVerification` consumed by the Contract, and the audit-log chain tip — `sealed_at` is stamped to the current server time, `evidence_strength_score` is recomputed in the final pass that may apply the notary bonus, and an `AuditLog` row with action `EVIDENCE_SEALED` is appended.

Exporting follows a successful seal. The package must be in `SEALED`, and the acting role must be `EvidenceArchivist`. On success, `exported_at` is stamped and an `AuditLog` row with action `EVIDENCE_EXPORTED` is appended; the package transitions `SEALED → EXPORTED`. As noted in §2.10, an export attempted before seal commits sees a non-`SEALED` package and is rejected with `ERR_INVALID_STATE`.

## 4. Endpoint Definitions

The following endpoints implement the workflows described in §3. New resources are returned with HTTP 201 Created; modifications and reads are returned with HTTP 200 OK. Failures are returned with the HTTP status mapped to each `error_id` in §5.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /templates | Create a new Template. | TemplateAdmin |
| GET | /templates | List Templates with optional filters. | TemplateAdmin, ContractInitiator, EvidenceArchivist, PlatformAdmin |
| GET | /templates/{id} | Read a single Template. | TemplateAdmin, ContractInitiator, EvidenceArchivist, PlatformAdmin |
| PATCH | /templates/{id} | Update mutable Template fields with OCC. | TemplateAdmin |
| POST | /templates/{id}/versions | Upload a new TemplateVersion (DRAFT). | TemplateAdmin |
| GET | /templates/{id}/versions | List TemplateVersions of a Template. | TemplateAdmin, ContractInitiator, EvidenceArchivist, PlatformAdmin |
| GET | /templates/{id}/versions/{vid} | Read a single TemplateVersion. | TemplateAdmin, ContractInitiator, EvidenceArchivist, PlatformAdmin |
| PATCH | /templates/{id}/versions/{vid} | Edit a DRAFT TemplateVersion with OCC. | TemplateAdmin |
| POST | /templates/{id}/versions/{vid}/publish | Publish a DRAFT TemplateVersion. | TemplateAdmin |
| POST | /templates/{id}/versions/{vid}/deprecate | Deprecate a PUBLISHED TemplateVersion. | TemplateAdmin |
| POST | /contracts | Create a Contract in DRAFT from a PUBLISHED TemplateVersion. | ContractInitiator |
| GET | /contracts | List Contracts with filters. | ContractInitiator, EvidenceArchivist, PlatformAdmin |
| GET | /contracts/{id} | Read a single Contract. | ContractInitiator, Signer, EvidenceArchivist, PlatformAdmin |
| PATCH | /contracts/{id} | Update DRAFT Contract with OCC. | ContractInitiator |
| POST | /contracts/{id}/signing-steps | Append a SigningStep to a DRAFT Contract. | ContractInitiator |
| POST | /contracts/{id}/signing-steps/{sid}/parties | Add a SigningParty to a step on a DRAFT Contract. | ContractInitiator |
| POST | /contracts/{id}/activate | Activate a DRAFT Contract. | ContractInitiator |
| POST | /contracts/{id}/void | Manually void a Contract. | ContractInitiator |
| GET | /contracts/{id}/progress | Return signing-progress query (chronological default). | ContractInitiator, Signer, EvidenceArchivist, PlatformAdmin |
| GET | /contracts/{id}/audit-logs | Historical audit-log retrieval, ordered by occurred_at ASC. | ContractInitiator, EvidenceArchivist, PlatformAdmin |
| POST | /signing-parties/{id}/sign | Signer commits a signature. | Signer |
| POST | /signing-parties/{id}/decline | Signer declines. | Signer |
| POST | /identity-verifications | Create an IdentityVerification record. | Signer, ContractInitiator |
| GET | /identity-verifications/{id} | Read an IdentityVerification. | Signer, ContractInitiator, EvidenceArchivist, PlatformAdmin |
| POST | /contracts/{id}/reminder-rules | Define a ReminderRule for a Contract. | ContractInitiator |
| PATCH | /reminder-rules/{rid} | Update a ReminderRule with OCC. | ContractInitiator |
| POST | /reminder-rules/{rid}/fire | Fire a single reminder slot. | ContractInitiator, SystemSweeper |
| GET | /contracts/{id}/reminder-events | List ReminderEvent rows under a Contract. | ContractInitiator, EvidenceArchivist, PlatformAdmin |
| GET | /contracts/{id}/evidence | Read EvidencePackage. | ContractInitiator, EvidenceArchivist, PlatformAdmin |
| GET | /contracts/{id}/evidence/preview | Provisional pre-seal evidence_strength_score. | ContractInitiator, EvidenceArchivist, PlatformAdmin |
| POST | /contracts/{id}/evidence/seal | Seal the EvidencePackage. | EvidenceArchivist |
| POST | /contracts/{id}/evidence/export | Export judicial-use evidence package. | EvidenceArchivist |
| POST | /_clock/advance | Test hook: advance the server clock to a given instant. | PlatformAdmin |
| POST | /_sweep/run | Test hook: run the periodic sweep. | PlatformAdmin, SystemSweeper |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_VALIDATION_FAILED | 400 |
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_TEMPLATE_PERMISSION_DENIED | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_VERSION_CONFLICT | 409 |
| ERR_INVALID_STATE | 409 |
| ERR_TEMPLATE_NOT_PUBLISHED | 409 |
| ERR_PARTY_NOT_ACTIVE | 409 |
| ERR_CONTRACT_EXPIRED | 409 |
| ERR_DUPLICATE_REMINDER | 409 |
| ERR_WORKFLOW_LOCKED | 409 |
| ERR_REINITIATE_INVALID | 409 |
| ERR_AUTH_FACTORS_INSUFFICIENT | 422 |
| ERR_DELEGATION_INVALID | 422 |
| ERR_TIMESTAMP_HASH_MISMATCH | 422 |
| ERR_TIMESTAMP_DRIFT_EXCEEDED | 422 |
| ERR_LEGAL_REP_REQUIRES_MFA | 422 |
| ERR_NOTARY_REFERENCE_REQUIRED | 422 |
