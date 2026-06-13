# Provider Credentialing API — Product Requirements Document

## 1. Introduction

Healthcare organizations and Credentialing Verification Organizations (CVOs) carry a legal and contractual obligation to confirm that every practitioner they sponsor is who they claim to be, holds the licenses they claim to hold, and is not barred from participating in federal health programs. This API governs that obligation end to end. It models the intake of a provider's application (anchored to a CAQH ProView attestation), the primary-source verification of each license, DEA registration, and board certification, the continuous monitoring of OIG and SAM exclusion lists, the convening of a peer-review committee, and the downstream enrollment of cleared providers onto payer panels.

The system is built around a single derived truth: a provider's **credentialing posture**. Rather than being toggled by hand, this posture is recomputed from the underlying facts on file — the verification state of each credential, the presence of open sanctions hits, the expiration banding of licenses against a deterministic clock, and the outcome of peer review. Because credentials expire and exclusion lists change, the posture is intrinsically time-sensitive: a provider cleared today can lapse tomorrow when a license crosses its expiration boundary, and that single change must cascade downward to terminate the panel enrollments that the lapse no longer supports. The platform therefore exposes an administrative clock so that these time-driven transitions can be exercised deterministically.

Three structural concerns shape the design. First, **segregation of duties**: the specialist who assembles a provider's file must not be permitted to vote on that same provider's peer review. Second, **optimistic concurrency**: committee decisions are recorded against an expected file version so that a chair never finalizes against a tally that a late-arriving vote has already changed. Third, a **cyclic re-credentialing loop**: clearance is not permanent but must be renewed on a fixed cycle, and the renewal path re-opens verification only for the credentials that need it.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting user, and `X-User-Role` declares the operational capacity under which they are acting. If either header is missing, or if `X-User-Role` does not name a role the system recognizes, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 401). When the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The system recognizes exactly six roles: `SystemAdmin`, `CredentialingSpecialist`, `MedicalDirector`, `PeerReviewer`, `EnrollmentCoordinator`, and `ComplianceOfficer`.

- A `SystemAdmin` is the platform operator. This role creates credentialing organizations, payers, sanctions sources, and peer reviewers, and is the only role that controls the deterministic clock.
- A `CredentialingSpecialist` owns provider intake, CAQH application submission, credential-item management, and primary-source verification.
- A `MedicalDirector` chairs peer review, opening and finalizing credentialing files, and may register reviewers and cast a committee ballot.
- A `PeerReviewer` is a committee member who casts weighted peer-review ballots.
- An `EnrollmentCoordinator` owns the payer-enrollment lifecycle and panel management.
- A `ComplianceOfficer` owns OIG/SAM sanctions screening and resolution.

All six roles share an **opaque** identity model. In every case, `X-User-ID` is an operator identifier that is not the primary key of any persisted entity, and the server never compares it to any resource's `id`. The server does, however, record it where the workflow demands an accountability anchor. Specifically, when a `CredentialingSpecialist` submits a provider's application, the server pins that operator's `X-User-ID` onto the provider as `initiated_by_user_id`; when a `MedicalDirector` opens peer review, their `X-User-ID` is recorded on the file as `chair_user_id`; and when any reviewer casts a ballot, their `X-User-ID` is recorded on the vote as `voter_user_id`. These recorded identifiers drive the segregation-of-duties and chair-tie-break logic described in §3, but they remain opaque operator strings, never foreign keys to a user entity.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and System Identifiers

Every primary resource in the system — credentialing organizations, payers, sanctions sources, providers, credential items, verification requests, sanctions screenings, credentialing files, peer reviewers, peer-review votes, and payer enrollments — carries a standard set of system-managed fields. Each of these entities is created with `common_fields` semantics, meaning all of them include the full set described below.

- `id` (string): a unique, server-minted identifier formatted as a UUID, carrying no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, recorded when the resource is first created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every modification to the resource.
- `version` (integer): a server-managed integer that begins at its initial value and increments by one on every mutation to the resource.

When a derived field is recomputed on a resource — for example, when a provider's `credentialing_status`, `readiness_score`, `sanction_score`, `credentialing_completed_date`, or `recred_due_date` changes, or when a file's `tally_yes` or `tally_no` is rewritten — that recomputation is itself a mutation: it refreshes `updated_at` and increments `version` on the entity that changed.

### 2.5. Nested Resource Retrieval and Path Validation

A great many endpoints address a child resource through its parent's identifier — for instance, a provider's credential items, a credential item's verification requests, or a credentialing file's votes. For any such request, the server validates the existence of each path identifier in left-to-right order. The request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the *first* identifier in the path that does not correspond to an existing resource, before any deeper resource is consulted and before any body-level validation runs. A request naming a verification request under a credential item that does not exist therefore fails on the missing credential item, not on the verification request.

Body-level foreign keys are validated separately and after path identifiers. When a request body carries a reference such as `payer_id`, `reviewer_id`, or `sanctions_source_id`, that reference must resolve to an existing resource that belongs to the same organization as the operation's context; a missing or cross-organization reference is rejected with `ERR_REFERENCED_RESOURCE_NOT_FOUND` (HTTP 404).

### 2.6. Validation Ordering

When several checks could reject the same request, they are evaluated in a fixed precedence so that the returned error is deterministic. The order is: (1) user-context authentication via the two headers (`ERR_MISSING_OR_INVALID_USER_CONTEXT`); (2) role authorization for the operation (`ERR_INSUFFICIENT_PERMISSIONS`); (3) existence of every path-referenced resource, left to right (`ERR_NOT_FOUND`); (4) existence of body foreign keys within the organization (`ERR_REFERENCED_RESOURCE_NOT_FOUND`); (5) request-body well-formedness, including required fields, correct types, valid enum members, the ten-digit NPI rule, and the rule that a credential item's expiration must fall strictly after its issue date (`ERR_INVALID_REQUEST`); (5.5) the credential-item interval-overlap check (`ERR_CREDENTIAL_INTERVAL_OVERLAP`); (6) on the file-finalize endpoint, the optimistic-concurrency version check (`ERR_STALE_VERSION`); (7) the target resource being in the state required for the requested transition (the transition-specific `ERR_*_NOT_*` codes); and then the remaining business checks. The duplicate-payer-enrollment check (`ERR_DUPLICATE_PAYER_ENROLLMENT`) sits in the temporal-constraint band alongside the credential-interval check. This precedence matters: on the finalize endpoint in particular, the version check runs *before* any downstream business check, so a stale version surfaces as `ERR_STALE_VERSION` rather than being masked by a quorum or outcome-mismatch failure.

### 2.7. The Deterministic Clock and Time-Driven Recomputation

Every credentialing organization owns a deterministic system clock, exposed as `current_utc` on the organization and initialized to `2026-01-01T00:00:00.000Z` when the organization is created. This clock never advances on its own; it moves only when a `SystemAdmin` sets it through the administrative clock capability, supplying the new instant as `to_iso8601`. The capability sets `current_utc` to the supplied value and then performs a chain of recomputations:

1. Every credential item's `expirable_band` is recomputed against the new clock, and an item may transition into `LAPSED`.
2. The `credentialing_posture` and `readiness_score` of every affected provider are recomputed; a newly `LAPSED` item demotes a previously `CLEARED` provider to `CONDITIONAL`.
3. Any provider whose `recred_state` is `CURRENT` and whose `recred_due_date` is now at or before `current_utc` transitions to `RECRED_DUE`, and its posture is recomputed to `CONDITIONAL`.
4. Any provider whose `credentialing_status` leaves `CLEARED` as a result of the above has each of its `ACTIVE` payer enrollments automatically terminated, as the closing link of the cascade described in §3.

This is the engine that makes a credential lapse propagate, in a single clock advance, all the way from a license's expiration to the termination of a payer panel slot.

### 2.8. Expirable Banding of Credentials

Each credential item carries a computed `expirable_band` that classifies how close it is to expiry, relative to the organization's `current_utc`. The number of whole days remaining is computed as the difference between the item's `expiration_date` and the organization's `current_utc`, expressed in milliseconds, divided by the number of milliseconds in one day (86,400,000) and then floored toward negative infinity to a whole number of days.

The band is then assigned as follows. If the days remaining is below zero, the band is `LAPSED`. Otherwise, if the days remaining is less than or equal to the organization's `expiring_soon_window_days` (which defaults to 90), the band is `EXPIRING_SOON`. Otherwise the band is `VALID`. The boundary is inclusive on the `EXPIRING_SOON` side: a credential with days remaining exactly equal to the window (90 by default) is `EXPIRING_SOON`, while days remaining equal to the window plus one (91 by default) is `VALID`. At the lower edge, days remaining of exactly zero is `EXPIRING_SOON`, and days remaining of negative one is `LAPSED`. This banding is computed when a credential item is created, whenever the clock advances, and whenever a provider's posture is recomputed.

### 2.9. Precision and Rounding

The provider readiness score is a numeric value carried to exactly two decimal places, rounded using the round-half-up convention. All weighted tallies, sanction scores, severity weights, vote weights, panel capacities, and cycle-day counts are integers and are computed in exact integer arithmetic with no rounding. Day-count arithmetic for expirable banding and re-credentialing due dates is performed in whole UTC days, each treated as exactly 86,400,000 milliseconds, with the floor (truncation toward negative infinity) applied where a fractional day would otherwise result.

### 2.10. Optimistic Concurrency Control on File Finalization

Finalizing a credentialing file is the one operation in this system guarded by optimistic concurrency. The finalize request must carry `expected_credentialing_file_version`, and this field is not optional on that operation. Its value is the `version` of the credentialing file that the chair last observed. Before any quorum, outcome, or state check runs, the server compares `expected_credentialing_file_version` against the file's current `version`. If they do not match, the finalize is rejected with `ERR_STALE_VERSION` (HTTP 412).

The reason this guard exists is that casting a ballot mutates the file: each cast vote recomputes the weighted tally and writes the new `tally_yes` and `tally_no` back onto the file, which increments the file's `version`. If a reviewer casts a ballot after the chair last read the file, the file's version advances. A finalize that still carries the chair's older expected version is then rejected on the stale-version check rather than being allowed to act on a tally that has since changed. No other endpoint accepts or requires a version field.

## 3. Business Logic & Workflows

### 3.1. Organizations, Payers, Sanctions Sources, and Reviewers

Everything in the system is scoped to a **credentialing organization**, created by a `SystemAdmin` with a `name`. At creation the organization may also specify its re-credentialing cycle length as `recred_cycle_days` (defaulting to 1095 days, i.e., three years) and the window at which credentials begin flagging as expiring via `expiring_soon_window_days` (defaulting to 90 days). The organization's `current_utc` is initialized as described in §2.7 and can be read back along with the rest of the organization record.

A `SystemAdmin`, or an `EnrollmentCoordinator`, registers a **payer** under an organization by supplying its `org_id`, a `name`, and a `payer_type` that must be one of `COMMERCIAL`, `MEDICARE`, or `MEDICAID`. The payer declares a `panel_capacity`, the maximum number of simultaneously `ACTIVE` enrollments its panel will admit, which must be at least 1. A payer also carries a `retroactive_allowed` flag (default false) that governs how coverage effective dates are computed at activation, as detailed in §3.6. Payers can be listed, optionally filtered by `org_id`, and read individually.

A `SystemAdmin` or `ComplianceOfficer` registers a **sanctions source** with an `org_id`, a `source_code` that must be one of `OIG_LEIE` or `SAM_EXCLUSIONS` and is unique within the organization, and a `severity_weight` — a positive integer applied to any hit recorded against this source when the provider's exclusion score is computed. Sanctions sources can be listed (optionally filtered by `org_id`) and read individually.

Peer reviewers are registered by a `SystemAdmin` or `MedicalDirector` against an organization, supplying the reviewer's `org_id`, the `user_id` the reviewer acts under (the `X-User-ID` value that this reviewer, acting as `MedicalDirector` or `PeerReviewer`, will present), the reviewer's `full_name`, and an optional `vote_weight` that defaults to 1 and must be a positive integer. This weight is what gives each reviewer's ballot its pull in the committee tally. Reviewers can be listed, optionally filtered by `org_id`, and read individually.

### 3.2. Provider Intake and the Application Lifecycle

A `CredentialingSpecialist` opens a provider's record by supplying the provider's `org_id`, a `npi` (the ten-digit National Provider Identifier, unique within the organization), a `full_name`, a `specialty`, and optionally the `caqh_id` that links to the provider's CAQH ProView attestation. A freshly created provider begins with `application_status` of `DRAFT`, a derived `credentialing_status` of `PENDING`, and a `recred_state` of `NOT_CLEARED`. Its `readiness_score` starts at 0 and its `sanction_score` at 0; `credentialing_completed_date` and `recred_due_date` are null until the provider is first cleared. The provider also carries an `initiated_by_user_id` that is empty until the application is submitted.

The intake application advances through a linear lifecycle: `DRAFT` to `SUBMITTED` to `IN_VERIFICATION` to `READY_FOR_REVIEW`. Submitting the application moves it from `DRAFT` to `SUBMITTED` and is permitted only when the application is currently `DRAFT` (otherwise `ERR_APPLICATION_NOT_DRAFT`), when the provider has a non-empty `caqh_id` on file (otherwise `ERR_CAQH_REQUIRED`), and when at least one credential item of type `STATE_LICENSE` already exists for the provider (otherwise `ERR_NO_LICENSE_ON_FILE`). On submission the server pins `initiated_by_user_id` to the submitting specialist's `X-User-ID`, establishing the segregation-of-duties anchor used later at peer review.

Beginning verification moves the application from `SUBMITTED` to `IN_VERIFICATION` and is permitted only when the application is currently `SUBMITTED` (otherwise `ERR_APPLICATION_NOT_SUBMITTED`). As a cascade, every credential item that is still `UNVERIFIED` is moved to `PENDING_PSV`, fanning the file out into primary-source verification.

Finalizing verification moves the application from `IN_VERIFICATION` to `READY_FOR_REVIEW` and is permitted only when the application is currently `IN_VERIFICATION` (otherwise `ERR_APPLICATION_NOT_IN_VERIFICATION`) and when no credential item remains in `PENDING_PSV` (otherwise `ERR_VERIFICATIONS_INCOMPLETE`). On finalization the provider's posture is recomputed, which sets `credentialing_status` and `readiness_score` to reflect the now-complete verification picture.

### 3.3. Credential Items and Primary-Source Verification

Within a provider's file, a `CredentialingSpecialist` records each **credential item** — a license, registration, or certification — by supplying its `item_type` (one of `STATE_LICENSE`, `DEA_REGISTRATION`, or `BOARD_CERTIFICATION`), its `identifier` (the license, DEA, or board certification number), an `issued_date`, and an `expiration_date`. The expiration must fall strictly after the issue date, or the create is rejected with `ERR_INVALID_REQUEST`. Each item begins in `verification_state` `UNVERIFIED`, and its `expirable_band` is computed immediately per §2.8. The item also records its owning `provider_id`.

A provider may not hold two credential items of the **same** `item_type` whose validity intervals overlap. Each item's validity interval runs from its `issued_date` to its `expiration_date` and is treated as closed at both ends, with adjacency allowed: if one item's `expiration_date` falls exactly on another item's `issued_date`, the two merely touch at a single instant and do not overlap. Any interior overlap — where the first item's issue date precedes the second's expiration date *and* the second item's issue date precedes the first's expiration date, both strictly — is a conflict and is rejected with `ERR_CREDENTIAL_INTERVAL_OVERLAP` (HTTP 409). This check applies only to items of the same type for the same provider.

A credential item's primary-source verification dimension moves through `UNVERIFIED`, then `PENDING_PSV`, then either `VERIFIED` or `REJECTED`. The transition from `UNVERIFIED` to `PENDING_PSV` happens as the cascade of beginning verification on the parent provider, described in §3.2. To drive verification, the specialist opens a **verification request** against a credential item, supplying the `method` (one of `PRIMARY_SOURCE` or `DESIGNATED_AGENT`) and a `source_reference` (the URL or registry reference consulted). A new verification request begins with `status` of `OPEN` and a null `verified_at`, and records its owning `credential_item_id` and `provider_id`.

Completing a verification request carries an `outcome` of either `PASS` or `FAIL`. A completion is permitted only when the owning verification request is currently `OPEN` (otherwise `ERR_VERIFICATION_NOT_OPEN`). A `PASS` completion additionally requires that the credential item's `expirable_band` is not `LAPSED`; a lapsed credential cannot be passed and is rejected with `ERR_CREDENTIAL_LAPSED` (HTTP 409). On a `PASS`, the request moves to `COMPLETED_PASS`, its `verified_at` is set to the organization's `current_utc`, and the credential item's `verification_state` becomes `VERIFIED`. On a `FAIL`, the request moves to `COMPLETED_FAIL`, its `verified_at` is set to `current_utc`, and the credential item's `verification_state` becomes `REJECTED`. The `FAIL` path carries no expirable-band precondition — only the open-request precondition applies to it. Either completion recomputes the provider's posture and readiness score.

When a credential item has been rejected, the specialist can re-open it for another attempt. Re-verification is permitted only when the item's `verification_state` is currently `REJECTED` (otherwise `ERR_ITEM_NOT_REJECTED`); it returns the item to `PENDING_PSV` and creates a fresh verification request in `OPEN` status, closing the revert loop so the item can be verified again.

### 3.4. Sanctions Screening and Exclusion

A `ComplianceOfficer` records an OIG/SAM **sanctions screening** for a provider by supplying the `sanctions_source_id` that identifies which list was checked, a `result` of either `CLEAR` or `HIT`, and optionally a `resolution_note`. The screening captures the organization's `current_utc` as its `screened_at`, begins in `status` `OPEN`, and records its owning `provider_id`. A `HIT` remains `OPEN` and continues to weigh against the provider until it is resolved; a `CLEAR` result contributes nothing to exclusion.

A provider's `sanction_score` is the sum of the `severity_weight` of the sanctions source behind every screening that is both a `HIT` and still `OPEN`. Screenings that are `RESOLVED`, and all `CLEAR` results, are excluded from this sum. Recording a `HIT` recomputes the score and the provider's posture, which drives the provider toward the `EXCLUDED` posture whenever the score is above zero.

A `ComplianceOfficer` resolves an open hit by supplying a `resolution_note`. Resolution is permitted only when the screening is currently `OPEN` (otherwise `ERR_SCREENING_NOT_OPEN`) and only when a non-empty `resolution_note` is provided (otherwise `ERR_RESOLUTION_NOTE_REQUIRED`, HTTP 400). On resolution the screening moves to `RESOLVED`, and the provider's `sanction_score` is recomputed. If that recomputation brings the score to zero and the provider has no `LAPSED` credential items, the provider is no longer held in the `EXCLUDED` posture.

### 3.5. Peer Review: Files, Votes, and Committee Decisions

A credentialing file is the peer-review packet for a provider. Either a `CredentialingSpecialist` or a `MedicalDirector` opens a file for a provider; it begins in `review_status` `ASSEMBLING` and records its owning `provider_id`. Its weighted tallies `tally_yes` and `tally_no` both begin at 0, and its `decision_reason` is empty until the file is finalized.

A `MedicalDirector` opens the file for review, moving it from `ASSEMBLING` to `UNDER_REVIEW`. This is permitted only when the file is currently `ASSEMBLING` (otherwise `ERR_FILE_NOT_ASSEMBLING`), when the parent provider's `application_status` is `READY_FOR_REVIEW` (otherwise `ERR_PROVIDER_NOT_READY`), and when the provider's `credentialing_status` is not `EXCLUDED` (otherwise `ERR_PROVIDER_EXCLUDED`, HTTP 403). A provider with any open OIG/SAM hit — that is, a `sanction_score` above zero — is in the `EXCLUDED` posture and cannot have a review opened. On opening, the file's `opened_at` is set to `current_utc` and its `chair_user_id` is set to the opening director's `X-User-ID`, establishing chair authority for the tie-break described below.

Committee members cast ballots on a file under review. A ballot may be cast by a `MedicalDirector` or a `PeerReviewer`, supplying the `reviewer_id` identifying the registered reviewer, a `ballot` of `YES`, `NO`, or `ABSTAIN`, and an optional `comment`. Each resulting vote records the `credentialing_file_id` of the file it belongs to, and the casting user's `X-User-ID` is recorded as `voter_user_id` on the vote. Casting then recomputes the weighted tally and writes the new `tally_yes` and `tally_no` onto the file, and increments the file's `version` by one. Votes may be listed for a file, listed across the system filtered by `reviewer_id` or `credentialing_file_id`, or read individually. Three guards protect a cast:

- The reviewer named by `reviewer_id` must belong to the same organization as the file's provider; otherwise the cast is rejected with `ERR_REVIEWER_ORG_MISMATCH` (HTTP 409).
- Segregation of duties forbids the casting user from being the provider's `initiated_by_user_id`: the specialist who submitted the application may not vote on that provider's review, and a violating cast is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).
- A reviewer may cast at most one vote on any given file; a second cast by the same reviewer on the same file is rejected with `ERR_DUPLICATE_VOTE` (HTTP 409).

The **weighted tally** is computed in a pinned order so that the chair's influence is well-defined even though the chair's own weight depends on the tally. First, the non-chair base is summed: `base_yes` is the total `vote_weight` of all reviewers whose ballot is `YES` and whose `voter_user_id` is not the file's `chair_user_id`, and `base_no` is the corresponding total for `NO` ballots cast by non-chair voters. An `ABSTAIN` ballot contributes nothing, and the chair's own ballot is excluded from this base. Second, the chair's contribution is applied: if the chair voted, take the chair's `vote_weight`; if the non-chair base is tied (`base_yes` equals `base_no`), the chair's weight counts double — that is, the chair's `vote_weight` multiplied by 2 — on whichever side the chair voted; otherwise the chair's weight counts once. Third, the final tallies are formed by adding the chair's contribution to the appropriate side: `tally_yes` is `base_yes` plus the chair's contribution to the YES side, and `tally_no` is `base_no` plus the chair's contribution to the NO side. The committee outcome is `YES` when `tally_yes` is greater than `tally_no`, `NO` when `tally_no` is greater than `tally_yes`, and `NO` when the two are equal — a deadlock denies.

A `MedicalDirector` finalizes the review by supplying a `decision` of `APPROVE` or `DENY`, the `expected_credentialing_file_version` for the optimistic-concurrency guard described in §2.10, and optionally a `decision_reason`. Finalization is permitted only when the file is currently `UNDER_REVIEW` (otherwise `ERR_FILE_NOT_UNDER_REVIEW`). After the version check passes, the file must have at least three peer-review votes whose ballot is `YES` or `NO` — abstentions do not count toward quorum — or the finalize is rejected with `ERR_QUORUM_NOT_MET` (HTTP 409). The supplied decision must match the committee outcome: an `APPROVE` requires the tally to resolve to a `YES` outcome, and a `DENY` requires it to resolve to a `NO` outcome; a decision that contradicts the outcome is rejected with `ERR_REVIEW_OUTCOME_MISMATCH` (HTTP 409). Finalization itself increments the file's `version` by one.

On an `APPROVE`, the file moves to `APPROVED`, and the provider is cleared: the provider's `credentialing_status` becomes `CLEARED`, its re-credentialing loop advances to `CURRENT`, its `credentialing_completed_date` is set to `current_utc`, and its `recred_due_date` is computed as described in §3.7. On a `DENY`, the file moves to `DENIED`, the provider's `credentialing_status` becomes `CONDITIONAL`, and every payer enrollment for that provider currently in `REQUESTED` or `SUBMITTED` is cascaded to `REJECTED`.

### 3.6. Payer Enrollment, Panel Capacity, and Coverage Dates

An `EnrollmentCoordinator` requests a **payer enrollment** for a provider by supplying the target `payer_id`. The enrollment captures `current_utc` as its `requested_at`, begins in `status` `REQUESTED`, records its owning `provider_id`, and has a null `effective_date` until it is activated. A provider may not hold two enrollments with the same payer whose coverage windows overlap. Coverage here follows ongoing-singleton semantics: any non-terminal enrollment — one whose status is `REQUESTED`, `SUBMITTED`, or `ACTIVE` — occupies an open-ended window, so any second non-terminal enrollment with the same payer overlaps it and is rejected with `ERR_DUPLICATE_PAYER_ENROLLMENT` (HTTP 409), regardless of any date arithmetic. Only terminal enrollments — those that are `REJECTED` or `TERMINATED` — free the window so a new enrollment with that payer may be requested.

Enrollment advances linearly: `REQUESTED` to `SUBMITTED` to `ACTIVE`, with termination available from `ACTIVE`. Submitting an enrollment to the payer moves it from `REQUESTED` to `SUBMITTED` and is permitted only when it is currently `REQUESTED` (otherwise `ERR_ENROLLMENT_NOT_REQUESTED`) and when the provider's `credentialing_status` is `CLEARED` (otherwise `ERR_PROVIDER_NOT_CLEARED`).

Activating an enrollment moves it from `SUBMITTED` to `ACTIVE` and is permitted only when it is currently `SUBMITTED` (otherwise `ERR_ENROLLMENT_NOT_SUBMITTED`), when the provider's `credentialing_status` is still `CLEARED` (otherwise `ERR_PROVIDER_NOT_CLEARED`), and when the count of currently `ACTIVE` enrollments on the target payer is strictly less than that payer's `panel_capacity` (otherwise `ERR_PANEL_AT_CAPACITY`, HTTP 409). On activation the enrollment's `effective_date` is computed and the status becomes `ACTIVE`.

The **effective date** depends on the payer's `retroactive_allowed` flag, which selects between two variants over otherwise identical inputs. When `retroactive_allowed` is true, the enrollment is backdated: its `effective_date` is set to the provider's `credentialing_completed_date` (the retroactive variant). When `retroactive_allowed` is false, the enrollment is forward-dated: its `effective_date` is set to the organization's `current_utc` at the moment of activation (the prospective variant). The two branches read different anchor timestamps and so yield different coverage-eligible windows for the same enrollment.

Terminating an enrollment moves it from `ACTIVE` to `TERMINATED` and frees one panel slot on the payer. A manual termination by an `EnrollmentCoordinator` is permitted only when the enrollment is currently `ACTIVE` (otherwise `ERR_ENROLLMENT_NOT_ACTIVE`) and requires a non-empty `termination_reason` (otherwise `ERR_TERMINATION_REASON_REQUIRED`, HTTP 400). Termination can also happen automatically: when a provider's `credentialing_status` leaves `CLEARED` — demoted to `CONDITIONAL` or `EXCLUDED` — each of that provider's `ACTIVE` enrollments is terminated by the system, with its `termination_reason` set automatically to `CREDENTIALING_LAPSED`, again freeing one panel slot per terminated enrollment. This is the tail of the depth-three cascade in which a clock advance lapses a credential, the lapse demotes the provider out of `CLEARED`, and the demotion terminates the provider's active enrollments.

### 3.7. The Re-Credentialing Cycle and Readiness Posture

A provider's clearance is not permanent. The re-credentialing loop carries `recred_state` through `NOT_CLEARED`, `CURRENT`, `RECRED_DUE`, and `IN_RECREDENTIALING`, and is cyclic: from `IN_RECREDENTIALING` it returns to `CURRENT` when the provider is cleared again. When a file is approved while the provider's `credentialing_status` is `CLEARED`, the loop advances from `NOT_CLEARED` to `CURRENT`, the `credentialing_completed_date` is set to `current_utc`, and the `recred_due_date` is computed.

The **re-credentialing due date** projects forward from a base instant by the organization's `recred_cycle_days`, added as whole UTC days of 86,400,000 milliseconds each. Two variants select the base. In the default rolling variant — used at first clearing, or whenever the organization's `recred_cycle_days` has not changed since the last cycle — the base is the `credentialing_completed_date` of *this* clearing, so the next due date rolls forward from the most recent clearing. In the fixed-anniversary variant — used for re-credentialing cycles after the first, that is, when the provider's `recred_state` was `IN_RECREDENTIALING` at the moment of this clearing — the base is the *original* first `credentialing_completed_date` rather than the latest one, and the due date is the next multiple of `recred_cycle_days` after `current_utc` measured from that original anchor. The same inputs admit two valid bases and therefore two different due dates.

When the clock advances to or past a provider's `recred_due_date` while the provider is `CURRENT`, the provider transitions to `RECRED_DUE` and its posture is recomputed to `CONDITIONAL` (the re-credentialing lapse demotes the posture). To renew, a `CredentialingSpecialist` starts re-credentialing, which is permitted only when the provider's `recred_state` is `RECRED_DUE` (otherwise `ERR_RECRED_NOT_DUE`). Starting re-credentialing moves `recred_state` to `IN_RECREDENTIALING`, resets `application_status` to `IN_VERIFICATION`, and conditionally re-opens verification: every credential item that is `VERIFIED` but whose `expirable_band` is not `VALID` is returned to `PENDING_PSV`, so only the credentials that have aged are re-verified. When the renewed file is later approved while `recred_state` is `IN_RECREDENTIALING`, the loop closes back to `CURRENT`, `credentialing_completed_date` is refreshed to `current_utc`, and a new `recred_due_date` is computed (here via the fixed-anniversary variant).

The **credentialing posture** itself — the derived `credentialing_status` — is evaluated in a fixed first-match-wins order whenever it is recomputed (on finalize-verification, on any verification completion, on any sanctions screen or resolve, on a clock advance, and on file finalization):

1. If the provider's `sanction_score` is above zero, the posture is `EXCLUDED`.
2. Otherwise, if any credential item has `verification_state` `REJECTED`, the posture is `CONDITIONAL`.
3. Otherwise, if any credential item has `expirable_band` `LAPSED`, the posture is `CONDITIONAL`.
4. Otherwise, if the provider's `recred_state` is `RECRED_DUE`, the posture is `CONDITIONAL`.
5. Otherwise, if the latest credentialing file's `review_status` is `APPROVED` and every credential item has `verification_state` `VERIFIED`, the posture is `CLEARED`.
6. Otherwise the posture is `PENDING`.

The **readiness score** is a 0-to-100 figure recomputed on finalize-verification, on any verification completion, on a sanctions resolution, and on a clock advance. Let V be the count of credential items that are both `VERIFIED` and `VALID`, and let T be the total count of credential items (at least one exists by the submit precondition). The verified ratio is V divided by T. A sanction penalty is taken as the smaller of 40 and the provider's `sanction_score` multiplied by 5. A re-credentialing penalty of 15 applies when `recred_state` is `RECRED_DUE` and is zero otherwise. The evaluation order is pinned: first compute the base as 100 multiplied by the verified ratio, rounded half-up to two decimal places; then subtract the integer sanction penalty and the integer re-credentialing penalty from that base; and finally clamp the result at a floor of zero, so the `readiness_score` is the larger of zero and the rounded post-penalty figure (itself rounded half-up to two decimal places).

## 4. Endpoint Definitions

Operations that create a new, distinct resource return a `201 Created` status code. Operations that modify an existing resource — including all state-transition actions and the administrative clock advance — return a `200 OK` status code.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/credentialing-orgs` | Create a credentialing organization | SystemAdmin |
| GET | `/credentialing-orgs/{id}` | Get an organization (includes current_utc) | SystemAdmin, CredentialingSpecialist, MedicalDirector, EnrollmentCoordinator, ComplianceOfficer |
| POST | `/_clock/set_current_utc` | Set the deterministic system clock; recompute banding, recred demotion, posture | SystemAdmin |
| POST | `/payers` | Create a payer / health plan | SystemAdmin, EnrollmentCoordinator |
| GET | `/payers` | List payers (filter by org_id) | SystemAdmin, EnrollmentCoordinator, CredentialingSpecialist |
| GET | `/payers/{id}` | Get a single payer | SystemAdmin, EnrollmentCoordinator, CredentialingSpecialist |
| POST | `/sanctions-sources` | Register an OIG/SAM sanctions source | SystemAdmin, ComplianceOfficer |
| GET | `/sanctions-sources` | List sanctions sources (filter by org_id) | SystemAdmin, ComplianceOfficer |
| GET | `/sanctions-sources/{id}` | Get a single sanctions source | SystemAdmin, ComplianceOfficer |
| POST | `/providers` | Create a provider intake record | CredentialingSpecialist |
| GET | `/providers/{id}` | Get a provider (includes derived posture, score, due date) | CredentialingSpecialist, MedicalDirector, EnrollmentCoordinator, ComplianceOfficer, SystemAdmin |
| GET | `/providers` | List providers (filter by org_id) | CredentialingSpecialist, MedicalDirector, EnrollmentCoordinator, ComplianceOfficer, SystemAdmin |
| POST | `/providers/{id}/submit-application` | Submit the CAQH application | CredentialingSpecialist |
| POST | `/providers/{id}/begin-verification` | Begin primary-source verification | CredentialingSpecialist |
| POST | `/providers/{id}/finalize-verification` | Finalize verification | CredentialingSpecialist |
| POST | `/providers/{id}/start-recredentialing` | Start a re-credentialing cycle | CredentialingSpecialist |
| POST | `/providers/{id}/credential-items` | Add a credential item to a provider | CredentialingSpecialist |
| GET | `/providers/{id}/credential-items` | List a provider's credential items | CredentialingSpecialist, MedicalDirector, ComplianceOfficer, SystemAdmin |
| GET | `/credential-items/{id}` | Get a single credential item | CredentialingSpecialist, MedicalDirector, ComplianceOfficer, SystemAdmin |
| POST | `/credential-items/{id}/reverify` | Re-open verification on a rejected credential item | CredentialingSpecialist |
| POST | `/credential-items/{id}/verification-requests` | Open a verification request for a credential item | CredentialingSpecialist |
| GET | `/credential-items/{id}/verification-requests` | List verification requests for a credential item | CredentialingSpecialist, MedicalDirector, ComplianceOfficer, SystemAdmin |
| GET | `/verification-requests` | List verification requests (filter by provider_id) | CredentialingSpecialist, MedicalDirector, ComplianceOfficer, SystemAdmin |
| GET | `/verification-requests/{id}` | Get a single verification request | CredentialingSpecialist, MedicalDirector, ComplianceOfficer, SystemAdmin |
| POST | `/verification-requests/{id}/complete` | Complete a verification request with PASS or FAIL | CredentialingSpecialist |
| POST | `/providers/{id}/sanctions-screenings` | Record an OIG/SAM screening result for a provider | ComplianceOfficer |
| GET | `/providers/{id}/sanctions-screenings` | List a provider's sanctions screenings | ComplianceOfficer, CredentialingSpecialist, MedicalDirector, SystemAdmin |
| GET | `/sanctions-screenings` | List sanctions screenings (filter by source/provider) | ComplianceOfficer, SystemAdmin |
| GET | `/sanctions-screenings/{id}` | Get a single sanctions screening | ComplianceOfficer, CredentialingSpecialist, MedicalDirector, SystemAdmin |
| POST | `/sanctions-screenings/{id}/resolve` | Resolve an open HIT screening | ComplianceOfficer |
| POST | `/peer-reviewers` | Register a peer reviewer in an org | SystemAdmin, MedicalDirector |
| GET | `/peer-reviewers` | List peer reviewers (filter by org_id) | SystemAdmin, MedicalDirector, CredentialingSpecialist |
| GET | `/peer-reviewers/{id}` | Get a single peer reviewer | SystemAdmin, MedicalDirector, CredentialingSpecialist |
| POST | `/providers/{id}/credentialing-files` | Open a credentialing review packet for a provider | CredentialingSpecialist, MedicalDirector |
| GET | `/providers/{id}/credentialing-files` | List a provider's credentialing files | CredentialingSpecialist, MedicalDirector, ComplianceOfficer, SystemAdmin |
| GET | `/credentialing-files/{id}` | Get a credentialing file (includes tallies, version) | CredentialingSpecialist, MedicalDirector, ComplianceOfficer, SystemAdmin |
| POST | `/credentialing-files/{id}/open-review` | Open peer review | MedicalDirector |
| POST | `/credentialing-files/{id}/cast-vote` | Cast a peer-review ballot; recompute weighted tally | MedicalDirector, PeerReviewer |
| GET | `/credentialing-files/{id}/votes` | List votes on a credentialing file | MedicalDirector, CredentialingSpecialist, ComplianceOfficer, SystemAdmin |
| GET | `/votes/{id}` | Get a single peer-review vote | MedicalDirector, CredentialingSpecialist, ComplianceOfficer, SystemAdmin |
| GET | `/votes` | List peer-review votes (filter by reviewer/file) | MedicalDirector, CredentialingSpecialist, ComplianceOfficer, SystemAdmin |
| POST | `/credentialing-files/{id}/finalize` | Finalize the review with OCC version guard | MedicalDirector |
| POST | `/providers/{id}/payer-enrollments` | Request a payer enrollment for a provider | EnrollmentCoordinator |
| GET | `/providers/{id}/payer-enrollments` | List a provider's payer enrollments | EnrollmentCoordinator, CredentialingSpecialist, MedicalDirector, SystemAdmin |
| GET | `/payer-enrollments` | List payer enrollments (filter by payer_id) | EnrollmentCoordinator, SystemAdmin |
| GET | `/payer-enrollments/{id}` | Get a single payer enrollment | EnrollmentCoordinator, CredentialingSpecialist, MedicalDirector, SystemAdmin |
| POST | `/payer-enrollments/{id}/submit` | Submit enrollment to payer | EnrollmentCoordinator |
| POST | `/payer-enrollments/{id}/activate` | Activate enrollment; compute effective date | EnrollmentCoordinator |
| POST | `/payer-enrollments/{id}/terminate` | Terminate an active enrollment, freeing a panel slot | EnrollmentCoordinator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT` | 401 Unauthorized |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCED_RESOURCE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_CAQH_REQUIRED` | 400 Bad Request |
| `ERR_NO_LICENSE_ON_FILE` | 409 Conflict |
| `ERR_RESOLUTION_NOTE_REQUIRED` | 400 Bad Request |
| `ERR_TERMINATION_REASON_REQUIRED` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_APPLICATION_NOT_DRAFT` | 409 Conflict |
| `ERR_APPLICATION_NOT_SUBMITTED` | 409 Conflict |
| `ERR_APPLICATION_NOT_IN_VERIFICATION` | 409 Conflict |
| `ERR_VERIFICATIONS_INCOMPLETE` | 409 Conflict |
| `ERR_VERIFICATION_NOT_OPEN` | 409 Conflict |
| `ERR_ITEM_NOT_REJECTED` | 409 Conflict |
| `ERR_CREDENTIAL_LAPSED` | 409 Conflict |
| `ERR_RECRED_NOT_DUE` | 409 Conflict |
| `ERR_FILE_NOT_ASSEMBLING` | 409 Conflict |
| `ERR_FILE_NOT_UNDER_REVIEW` | 409 Conflict |
| `ERR_PROVIDER_NOT_READY` | 409 Conflict |
| `ERR_ENROLLMENT_NOT_REQUESTED` | 409 Conflict |
| `ERR_ENROLLMENT_NOT_SUBMITTED` | 409 Conflict |
| `ERR_ENROLLMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_SCREENING_NOT_OPEN` | 409 Conflict |
| `ERR_PROVIDER_EXCLUDED` | 403 Forbidden |
| `ERR_PROVIDER_NOT_CLEARED` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_DUPLICATE_VOTE` | 409 Conflict |
| `ERR_REVIEWER_ORG_MISMATCH` | 409 Conflict |
| `ERR_QUORUM_NOT_MET` | 409 Conflict |
| `ERR_REVIEW_OUTCOME_MISMATCH` | 409 Conflict |
| `ERR_PANEL_AT_CAPACITY` | 409 Conflict |
| `ERR_CREDENTIAL_INTERVAL_OVERLAP` | 409 Conflict |
| `ERR_DUPLICATE_PAYER_ENROLLMENT` | 409 Conflict |
