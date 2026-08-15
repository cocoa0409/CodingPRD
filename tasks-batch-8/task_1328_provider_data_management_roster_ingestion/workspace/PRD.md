# Provider Data Management API — Product Requirements Document

## 1. Introduction

A health plan's provider data office sits at the confluence of every upstream roster feed the organization receives — delegated group rosters, clearinghouse extracts, CAQH-style weekly files, FHIR bundles — and every downstream system that consumes provider truth: claims adjudication, the member-facing directory, and network management. Each feed arrives in its own format, asserts its own version of the same provider's demographics, specialties, practice addresses, contacts, and licenses, and arrives on its own cadence. When two feeds disagree, when a change is retroactively effective, or when the same practitioner appears under two slightly different identity triples, the office needs deterministic rules — not ad-hoc spreadsheets — to decide what the plan believes, from whom, and since when.

This document specifies the Provider Data Management (PDM) API, the system of record for that office. The API is mounted under `/pdm` and covers the full operating loop: registering upstream feeds with explicit conflict-adjudication precedence; ingesting roster files through a staged parse, normalize, validate, and commit pipeline; resolving row identity against the known provider population on the NPI, TIN, and location legs; maintaining effective-dated provider attributes with retroactive-change adjudication; scoring provider data quality; running attestation outreach when data goes stale; merging duplicate providers; and publishing quality-gated snapshots to downstream claims, directory, and network targets. All temporal reasoning in the system — effective dating, staleness, SLA windows, snapshot cutoffs — reads a server-maintained logical clock rather than wall-clock time, so behavior is deterministic and testable.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes four distinct roles: `IntakeOperator`, the roster intake operator who registers files and drives the parse, normalize, validate, and commit pipeline; `DataSteward`, the provider data steward who owns source configuration, identity adjudication, merges, retro approvals, conflict resolution, attestation campaigns, and quality recompute; `DistributionOperator`, who manages downstream targets and builds, publishes, acknowledges, and fails distribution batches; and `ProviderContact`, an external provider representative who responds to attestation outreach. A request whose `X-User-Role` header is missing or names no known role is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted for the endpoint, per the authorization column of the endpoint table in §4, is rejected with `ERR_FORBIDDEN` (HTTP 403).

For all four roles — `IntakeOperator`, `DataSteward`, `DistributionOperator`, and `ProviderContact` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server never compares `X-User-ID` to any entity's `id`. It does, however, record the opaque identifier where a workflow calls for it: the registrant's id is captured when a roster file is registered so the segregation-of-duties check can compare it against the committing operator's id, the committer's id is likewise remembered so the conflict-adjudication duty check can compare against it, and a merge record persists the deciding steward's id as `decided_by_user_id`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

Every temporal decision in the system — whether an attribute is in force, whether a feed has breached its freshness SLA, whether an attestation window has closed, what a distribution snapshot froze — is computed against a server-maintained **logical clock**. The logical clock never falls back to wall-clock time. At startup it reads exactly 2026-08-01T00:00:00Z, and it advances only when a `DataSteward` explicitly sets it through the clock-setting capability, whose request body carries the target instant as `to_iso8601` and whose response echoes the newly installed value as `current_utc`. Effective-date comparisons, staleness arithmetic, attestation deadlines, and snapshot cutoffs all read this clock and nothing else.

### 2.5. Common Resource Properties

All primary resources in the system — roster sources, roster files, roster rows, providers, provider attributes, provider aliases, attribute conflicts, distribution targets, distribution batches, attestation campaigns, and attestation requests — share a standard set of system-managed fields:

- **`id` (string):** A unique, server-minted identifier for the resource, formatted as a UUID with no type prefix.
- **`created_at` (string):** An ISO 8601 timestamp in UTC with three fractional digits (e.g., `2025-05-24T10:30:00.123Z`) indicating when the resource was first created.
- **`updated_at` (string):** An ISO 8601 UTC timestamp, again with three fractional digits, indicating when the resource was last modified; it refreshes upon any change to the resource's properties.
- **`version` (integer):** A system-managed integer that increments by one with every modification to the resource, and which anchors the optimistic concurrency checks described in §2.7.

Three record types are append-only ledger entries and carry only `id` and `created_at`: a distribution item, a data quality score row, and a provider merge record. For these three, both `updated_at` and `version` are absent — they are never mutated after creation.

### 2.6. Request Evaluation Order

Every request is evaluated against a fixed pipeline of validation layers, and the order matters whenever several failures coincide. Authentication comes first — a missing or unknown role yields `ERR_UNAUTHENTICATED` before anything else is examined. Authorization follows, with a role that may not call the endpoint rejected as `ERR_FORBIDDEN`. Next, path identifiers are resolved for existence and parentage, left to right, with any miss producing `ERR_NOT_FOUND`. Only then does the system ask whether the target resource sits in a state from which the requested transition exists; a request that names a legal resource in an illegal state is rejected with `ERR_INVALID_STATE` (HTTP 409). After state legality come the segregation-of-duties checks of §2.8, then the optimistic-concurrency checks of §2.7, and then the endpoint's remaining business rules, each family of which declares its own internal order in §3 — for example, on file commit the duty check surfaces before the stale-version check, which in turn surfaces before the unresolved-row-conflict check. Syntactic body validation — malformed payloads, missing required fields, invalid enum values, out-of-range integers — is evaluated last, after every applicable business rule, and surfaces as `ERR_INVALID_REQUEST` (HTTP 400).

### 2.7. Optimistic Concurrency Control

Three write operations carry optimistic concurrency control, and each guards a named parent entity whose `version` the client must prove it has observed.

- Committing a roster file — `POST /pdm/roster-files/{id}/commit` — requires the non-optional request field `expected_roster_file_version`, carrying the client's last observed `version` of the file. If the value does not match the file's current `version`, the commit is rejected with `ERR_STALE_VERSION` (HTTP 412): a prior commit attempt or a supersession has advanced the file's version, and the caller's view of the file's row-resolution state is stale.
- Executing a provider merge — `POST /pdm/provider-merges` — requires the non-optional field `expected_provider_version`, carrying the last observed `version` of the provider being folded in. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412): an intervening commit, retro approval, or merge has legitimately changed that provider's attribute set, and the merge decision was made against a snapshot the client can no longer defend.
- Approving a retro-effective attribute — `POST /pdm/provider-attributes/{id}/approve-retro` — requires the non-optional field `expected_provider_version`, carrying the last observed `version` of the owning provider. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412): the interval timeline the approver reviewed no longer matches the stored timeline.

Endpoints not listed here do not accept a version field at all.

### 2.8. Segregation of Duties in Stewardship

Two duty-separation rules keep intake and adjudication honest, and both compare opaque `X-User-ID` values only. First, the operator who registers a roster file may not be the one who commits it: registration records the registrant's opaque user id, and a commit attempt carrying the same id is rejected with `ERR_SOD_SAME_USER` (HTTP 403). Second, the steward who resolves an attribute conflict may not be the operator who committed the file that created the challenger attribute; an adjudication attempted by that operator is rejected with `ERR_SOD_ADJUDICATOR` (HTTP 403). Per §2.6, both checks run after state legality and before the stale-version and remaining business checks.

### 2.9. Nested Resource Retrieval

The API enforces strict, hierarchical validation for every request whose path nests one resource beneath another — a row inside a file, an attribute inside a provider, a request inside a campaign, an item inside a batch. Path identifiers are validated in sequential left-to-right order: the request is rejected immediately with `ERR_NOT_FOUND` (HTTP 404) at the first `id` in the path that does not correspond to an existing resource, or that exists but does not belong to the named parent chain. A request addressing a row beneath a file that does not exist therefore fails on the file before the row is ever examined.

### 2.10. Dates, Integers, and Rounding Discipline

Attribute effective dating operates at ISO date granularity — a calendar day, with no time component — and every interval comparison in §3.4 is a day-level comparison. Identity-resolution scores, precedence ranks, quality-score components, and change-set arithmetic are all integer computations with no intermediate rounding. Exactly one rounding step exists anywhere in the system: the completeness component of the quality score rounds half-up to a whole number, once, at its final multiplication. No monetary values exist in this domain, and no other rounding or truncation is permitted.

## 3. Business Logic & Workflows

### 3.1. Onboarding and Governing Upstream Feeds

Before any roster file can arrive, a `DataSteward` registers the feed that will deliver it. A **roster source** is registered with a unique short `source_code` (for example, `CAQH_WEEKLY`), a human-readable `display_name`, the feed's `format` — one of `CSV`, `XLSX`, `JSON`, `FHIR`, or `FIXED_WIDTH` — a `precedence_rank` used in conflict adjudication, and a `freshness_sla_days` value of at least 1, the number of days after which a provider attribute asserted only by this feed is considered stale. Optionally the steward may name a `default_attestation_campaign_id`, designating the campaign into which stale providers sourced from this feed are enrolled by default. A new source starts life with `status` `ACTIVE`.

The `precedence_rank` is the system's tie-break currency between disagreeing feeds: the lower the integer, the stronger the source's claim. The rank must be unique across all non-`RETIRED` sources, both at registration and when a source is later patched; a colliding rank is rejected with `ERR_PRECEDENCE_RANK_CONFLICT` (HTTP 409). After registration a steward may patch only the mutable profile — `precedence_rank`, `freshness_sla_days`, `display_name`, and `default_attestation_campaign_id` — and each patch increments the source's `version` by one; `source_code` and `format` are fixed at registration. Sources may be listed with optional `status`, `format`, and `default_attestation_campaign_id` filters alongside the standard pagination parameters.

A source's operational life moves between `ACTIVE`, `SUSPENDED`, and `RETIRED`. Suspension (`ACTIVE` → `SUSPENDED`) and retirement (`ACTIVE` → `RETIRED`) share a guard: neither may proceed while the source has a file anywhere in the inflight states `RECEIVED`, `PARSED`, `NORMALIZED`, or `VALIDATED`, and an attempt under those conditions is rejected with `ERR_SOURCE_HAS_INFLIGHT_FILE` (HTTP 409). Resumption returns a `SUSPENDED` source to `ACTIVE` without preconditions. Each of the three transitions increments the source's `version` by one. Retirement is terminal and cannot create a rank conflict, since retirement only withdraws a rank from the pool of non-`RETIRED` sources; its lasting consequence is that any roster row subsequently arriving under the retired source is rejected with `reject_reason` `SOURCE_RETIRED`. A source that is not `ACTIVE` may not accept new file registrations, a rule enforced with `ERR_SOURCE_NOT_ACTIVE` (HTTP 409).

### 3.2. Receiving, Parsing, and Normalizing Roster Files

An `IntakeOperator` registers an inbound roster file against its delivering feed by supplying the `roster_source_id`, the upstream file name or reference as `external_file_ref`, the sender-manifest row count as `declared_row_count` (zero or more), and the SHA-256 hex of the raw payload as `checksum`. Two uniqueness rules guard registration, and both yield `ERR_DUPLICATE_FILE` (HTTP 409): the pair of `external_file_ref` and `roster_source_id` must be unique, and the `checksum` must be unique within the same source. The check that the named source is `ACTIVE` — `ERR_SOURCE_NOT_ACTIVE` when it is not — is evaluated before the duplicate-file check. Registration stamps `received_at` from the logical clock, lands the file in `RECEIVED`, and records the registrant's opaque user id for the segregation-of-duties check at commit time. Files may be listed with optional `roster_source_id` and `status` filters.

Parsing a `RECEIVED` file materializes one **roster row** per parsed line. The source must still be `ACTIVE` at parse time — `ERR_SOURCE_NOT_ACTIVE` otherwise — and this check is evaluated before any row-count comparison. Each materialized row starts in `PENDING`, carries its zero-based position in the file as `row_index` (unique within the file), and preserves the original line verbatim as `raw_payload`. When the number of materialized rows differs from the manifest's `declared_row_count`, the parse call fails with `ERR_ROW_COUNT_MISMATCH` (HTTP 422) and the file falls directly to `REJECTED` rather than advancing. Otherwise the file advances `RECEIVED` → `PARSED` and its `parsed_row_count` records how many rows were materialized.

Normalization then walks every `PENDING` row and produces its `normalized_payload`: the canonical JSON form in which the NPI, TIN, and location fields have been coerced, alongside the extracted `npi` (a normalized ten-digit value, or the empty string when unparseable), `tin` (a normalized nine-digit value, or the empty string when unparseable), `location_key` (a normalized address hash built from the street line, city, state, and zip, used as the third identity leg), and the `effective_date` the row's attribute payload claims to take effect — which may lie in the past as a retroactive assertion or in the future. Rows that cannot survive normalization are rejected in place with a machine-readable cause recorded in `reject_reason`: an unparseable NPI rejects the row as `MALFORMED_NPI`, an unparseable TIN as `MALFORMED_TIN`, and an empty `location_key` as `MISSING_LOCATION`. When several rows within the same file normalize to the same triple of `npi`, `tin`, and `location_key`, only the row with the lowest `row_index` keeps its `PENDING` status; the rest are rejected as `DUPLICATE_IN_FILE`. With row-level adjudication complete, the file advances `PARSED` → `NORMALIZED` and its `rejected_row_count` is recomputed. A row's `reject_reason` is set if and only if the row's `status` is `REJECTED`.

A file that will never be committed can be rejected outright by the intake operator from any pre-commit state, landing in the terminal `REJECTED` state. The cascade depends on where the file stood: from `RECEIVED` there are no rows to touch; from `PARSED`, every `PENDING` row transitions to `REJECTED` with its `reject_reason` preserved, or set to `MALFORMED_NPI` when unset; from `NORMALIZED`, every remaining non-terminal row transitions to `REJECTED`; and from `VALIDATED`, no provider writes are rolled back because none have occurred yet. An individual `PENDING` row may also be rejected on its own by an `IntakeOperator`, who supplies the `reject_reason` in the request.

### 3.3. Resolving Provider Identity Across Rows

Validation runs identity resolution over every non-`REJECTED` row of a `NORMALIZED` file and advances the file to `VALIDATED`. The candidate pool for a row is every provider whose `lifecycle_status` is `ACTIVE` or `SUSPENDED` and who shares at least one identity leg with the row — an equal `npi`, an equal `tin`, or an equal `location_key`. Each candidate earns a match score from three weighted legs, summed with integer arithmetic: 50 points when the candidate's `npi` equals the row's `npi`, 30 points when the candidate's `tin` equals the row's, and 20 points when the candidate's `location_key` equals the row's. The decision then falls out of the score distribution. When exactly one candidate achieves a perfect score of 100, the row becomes `MATCHED`. When no candidate reaches 70, the row becomes `NEW_PROVIDER`. When exactly one candidate lands in the 70-through-99 band, the row becomes `MATCHED`, and at commit time the system records an alias for the winning provider whose `link_kind` is `AUTO_FUZZY` and whose `match_confidence` equals that winning candidate's score. When two or more candidates reach 70 — including the case of one perfect scorer alongside others at 70 or above — the row becomes `CONFLICT`. Ties between candidates holding equal top scores are broken in favor of the candidate with the earliest `created_at`; a tie that survives even that comparison sends the row to `CONFLICT`. Every `MATCHED` row records its provider in `resolved_provider_id`. Identity ambiguity at this stage never creates a conflict record — attribute conflicts arise only when attribute values are written — but a `CONFLICT` row blocks its owning file's commit until a steward resolves it.

Feeds registered with `format` `FHIR` resolve strictly. For their rows, only a perfect score of 100 produces `MATCHED`; any candidate scoring in the 70-through-99 band resolves the row to `CONFLICT` instead, and no `AUTO_FUZZY` alias is created.

Two steward actions clear a contested row. Linking a row — available while the row is `PENDING` or `CONFLICT` — points it at a provider named by `provider_id` in the request; the target provider's `lifecycle_status` must be `ACTIVE`, with violations rejected as `ERR_PROVIDER_NOT_LINKABLE` (HTTP 409). A successful link moves the row to `MATCHED`, sets its `resolved_provider_id`, and records an alias whose `link_kind` is `MANUAL`, capturing the row's observed identity legs as `alias_npi`, `alias_tin`, and `alias_location_key`. Alternatively, a steward may declare a `CONFLICT` row to be genuinely new, moving it to `NEW_PROVIDER`. `MATCHED`, `NEW_PROVIDER`, and `REJECTED` are the terminal row states. Rows can be browsed within their file or across files, with the cross-file listing accepting optional `roster_file_id`, `resolved_provider_id`, and `status` filters.

### 3.4. Committing Files and the Effective-Dated Attribute Timeline

Commit is the moment a `VALIDATED` file's assertions become the plan's provider truth, and it is the most heavily guarded transition in the system. Its checks are evaluated in a fixed order. The file must stand in `VALIDATED`, or the call fails with `ERR_INVALID_STATE`. The committing operator's opaque user id must differ from the registrant's, per §2.8, or the call fails with `ERR_SOD_SAME_USER`. The request must carry `expected_roster_file_version` matching the file's current `version`, per §2.7, or the call fails with `ERR_STALE_VERSION`. Finally, every row must be resolved — no row may remain in `PENDING`, and no row may remain in `CONFLICT` — or the call fails with `ERR_UNRESOLVED_ROW_CONFLICTS` (HTTP 409).

A successful commit writes through to the provider population. For each `NEW_PROVIDER` row the system creates a provider whose `lifecycle_status` is `ACTIVE`, carrying the row's `npi`, `tin`, and `location_key`, together with an initial attribute set; each new attribute materializes as `PENDING` and immediately lands in `ACTIVE` or `RETRO_PENDING` according to the dating rules below. For each `MATCHED` row the system upserts the row's attribute payload onto the matched provider, and a retro-effective insert transitions affected existing intervals to `SUPERSEDED` and opens attribute-conflict records when the incumbent's source differs from the challenger's, per §3.5. Every provider touched by the commit has its `last_roster_file_id` updated to this file and its `version` incremented, its quality score recomputed with a fresh score row appended, and its `current_quality_score` and `staleness_flag` refreshed per §3.7. The file itself settles its final `committed_row_count` — the number of rows whose identity resolution ended `MATCHED` or `NEW_PROVIDER` — alongside its final `rejected_row_count`, increments its own `version` by one, and rests in the terminal `COMMITTED` state.

Attribute values are effective-dated as half-open intervals: a value applies from its `effective_date`, inclusive, until its `term_date`, exclusive, and a null `term_date` means the value is open-ended. All interval arithmetic uses the day-level granularity of §2.10. Whenever a new value arrives for a given provider, group, and key — through a file commit, a manual addition, a retro approval, a conflict resolution, a merge, or an attestation correction — the system collects the incoming interval together with every existing `ACTIVE` interval for the same triple and applies the dating rules. The retro guard fires first: when the incoming interval's `effective_date` precedes every existing effective date in the group and applying it would rewrite the historically-first value, the incoming interval does not apply at all — it enters `RETRO_PENDING` and waits for steward adjudication. An incoming value whose `effective_date` is in the future relative to the logical clock simply remains `PENDING`, since no transition fires for it yet.

When the incoming interval does apply, two rewrite rules reconcile it against the existing timeline. Any existing interval that begins on or after the incoming `effective_date` is superseded when the incoming interval covers its whole span — which holds when the existing interval is open-ended, or its `term_date` falls on or before the incoming `term_date`, or the incoming interval is itself open-ended; each superseded interval is remembered on its replacement through `supersedes_attribute_id`. Any existing interval that begins strictly before the incoming `effective_date` and extends past it — open-ended, or with a `term_date` later than the incoming `effective_date` — is truncated instead: its `term_date` is rewritten to the incoming `effective_date` and it remains `ACTIVE` over the shortened span. After truncation, any interval whose `term_date` no longer sits strictly after its `effective_date` has zero length, and zero-length intervals never persist — they are superseded. One boundary case is deliberately gentle: when the incoming `effective_date` equals an existing interval's `term_date` exactly, the two intervals are adjacent rather than overlapping, so nothing is superseded, no conflict is raised, and both remain `ACTIVE`.

A retroactive insert that lands strictly inside an existing interval splits rather than truncates. When the incoming `effective_date` lies in the past relative to the logical clock and falls strictly inside an existing interval, the existing interval divides into two `ACTIVE` halves around the newcomer — a left half spanning from the original start up to but not including the incoming start, and a right half spanning from the incoming end up to but not including the original end, with the right half carrying the old value and an `effective_date` equal to the incoming `term_date`. When the incoming interval is open-ended, no right half is created and the old interval is only truncated.

A `DataSteward` disposes of each `RETRO_PENDING` attribute in one of two ways. Approving it — a call that must carry `expected_provider_version` matching the owning provider's current `version` and is otherwise rejected with `ERR_STALE_VERSION` — moves the attribute `RETRO_PENDING` → `ACTIVE`, re-runs the dating rules for the group so intervals may split, and increments the provider's `version` by one. Voiding it moves the attribute `RETRO_PENDING` → `VOIDED` with no interval rewrite at all.

Stewards also maintain the timeline directly. Manually adding an attribute to a provider takes the `attribute_group` — one of `DEMOGRAPHIC`, `SPECIALTY`, `PRACTICE_ADDRESS`, `CONTACT`, or `LICENSE` — the sub-key `attribute_key` (for example, `phone` or `primary_taxonomy`), the canonical `attribute_value`, the inclusive `effective_date`, and an optional `term_date`; when `term_date` is present it must fall strictly after `effective_date`, or the request fails with `ERR_INVALID_DATE_RANGE` (HTTP 422). The dating rules then apply, the attribute lands `ACTIVE` or `RETRO_PENDING`, and the provider's `version` increments. Correcting an attribute's `attribute_value` or `term_date` through the patch capability re-runs the dating rules for the group, enforces the same date-range rule, and again increments the provider's `version`. Every roster-originated attribute carries its provenance — the `roster_source_id` of the feed that asserted it and the `roster_row_id` of the row that carried it. Attribute listings support point-in-time review: the per-provider listing accepts optional `attribute_group`, `status`, and `as_of_date` filters, while the cross-provider listing accepts optional `provider_id`, `roster_source_id`, `roster_row_id`, `supersedes_attribute_id`, and `status` filters. The attribute state space is `PENDING`, `ACTIVE`, `RETRO_PENDING`, `SUPERSEDED`, and `VOIDED`, with `SUPERSEDED` and `VOIDED` terminal.

Once a committed file has been replaced, a steward may mark it superseded. The precondition is that a replacement file for the same `roster_source_id` exists in `VALIDATED` or `COMMITTED` state — otherwise the call is rejected with `ERR_NO_REPLACEMENT_FILE` (HTTP 409). Supersession moves the file `COMMITTED` → `SUPERSEDED` and increments its `version`, but it is a bookkeeping marker only: it does not mutate any provider.

### 3.5. Adjudicating Cross-Source Attribute Conflicts

Overlapping intervals for the same group and key that arrive from different roster sources never split the timeline; precedence decides instead, comparing integer `precedence_rank` values where the lower integer asserts the stronger claim. When the incumbent interval's source outranks the challenger's, the incumbent stands automatically — the challenger is `VOIDED` and no conflict record is created. When the challenger's source outranks the incumbent's, the challenger wins automatically — the incumbent becomes `SUPERSEDED` and the challenger becomes `ACTIVE`. Only when the two sources hold equal `precedence_rank` does the system open an **attribute conflict** in `OPEN` status for steward adjudication: the incumbent slot goes to the interval whose source was registered earlier — or, when both intervals came from the same source, to the interval created earlier — and the challenger interval stays `PENDING` until adjudication. Each conflict records the disputed `provider_id`, `attribute_group`, and `attribute_key`, the `incumbent_attribute_id` and `challenger_attribute_id` of the two value holders, and the `incumbent_source_id` and `challenger_source_id` of the disagreeing feeds, with its `resolution` starting at `PENDING`. Conflicts may be listed with optional `provider_id`, `status`, `incumbent_attribute_id`, `challenger_attribute_id`, `incumbent_source_id`, and `challenger_source_id` filters.

Resolution is a `DataSteward` act carrying a `resolution` of `KEEP_INCUMBENT`, `ACCEPT_CHALLENGER`, or `MERGE_VALUES`, with an optional `resolution_reason` for the adjudicator's free-text rationale — required whenever the resolution is anything other than `PENDING` — and an optional `resolved_value`. Three rules shape the outcome. Keeping the incumbent voids the challenger attribute. Accepting the challenger supersedes the incumbent and leaves the challenger in, or returns it to, `ACTIVE`. Merging values supersedes both and creates a fresh attribute carrying the supplied `resolved_value` with an `effective_date` equal to the logical clock date — and a merge resolution submitted without `resolved_value` is rejected with `ERR_MERGE_VALUE_REQUIRED` (HTTP 422). The adjudicator must not be the operator who committed the file that created the challenger attribute, per §2.8, or the call fails with `ERR_SOD_ADJUDICATOR`; this duty check is evaluated before the missing-value check. Every resolution re-runs the provider's quality scoring, since the conflict component may recover. Both `OPEN` → `RESOLVED` and `ESCALATED` → `RESOLVED` follow these same rules.

A conflict whose two sources are genuinely tied cannot be kicked upward: escalating a conflict whose sources hold equal `precedence_rank` is rejected with `ERR_PRECEDENCE_TIE_NOT_ESCALATABLE` (HTTP 409). Any other `OPEN` conflict may be escalated to `ESCALATED` to signal that it awaits a higher authority, and an escalated conflict resolves through exactly the same resolution path as an open one.

### 3.6. Provider Lifecycle, Aliases, and Duplicate Merges

A provider normally enters the system through a committed roster file, but a `DataSteward` may also create one directly — seeding the directory ahead of the first roster — by supplying the canonical `npi`, `tin`, and `location_key`. The `npi` is unique across all non-`MERGED` providers, the `tin` is deliberately not unique since a tax id is shared across practice locations, and the triple of `npi`, `tin`, and `location_key` is unique. A manually created provider starts with `lifecycle_status` `ACTIVE` and an initial quality-score run per §3.7. The provider listing accepts optional `lifecycle_status`, `npi`, `tin`, `staleness_flag`, `min_quality_score`, `merged_into_provider_id`, and `last_roster_file_id` filters.

Suspension moves a provider `ACTIVE` → `SUSPENDED`, withdraws every attestation request still in `SENT` status for that provider, excludes the provider from future distribution snapshots, and increments the provider's `version`. Reinstatement returns a `SUSPENDED` provider to `ACTIVE` — and only a `SUSPENDED` provider may be reinstated, with other states failing as `ERR_INVALID_STATE` — but it is gated on quality: the provider's `current_quality_score` must be at least the lowest `required_quality_floor` across all `ACTIVE` distribution targets, or the call is rejected with `ERR_QUALITY_FLOOR_NOT_MET` (HTTP 409). Termination moves a provider `ACTIVE` → `TERMINATED` and is blocked while any attestation request for the provider remains in `SENT` — `ERR_OPEN_ATTESTATION_EXISTS` (HTTP 409) — so outreach is never orphaned mid-flight. Termination closes the provider's book: every open-ended attribute interval, one whose `term_date` is null, receives a `term_date` equal to the logical clock date; every open conflict is resolved automatically as `RESOLVED` with `resolution` `KEEP_INCUMBENT` and `resolution_reason` set to "provider terminated"; the provider's `version` increments; and the next distribution snapshot carries a `TERM` item for the provider.

Aliases record the observed identity variants that identity resolution or steward judgment has folded onto a canonical provider — the observed `alias_npi`, `alias_tin`, and `alias_location_key` — together with the `match_confidence` assigned at link time, an integer from 0 to 100, and a `link_kind` of `AUTO_EXACT` for system-resolved exact links, `AUTO_FUZZY` for system-resolved fuzzy links, or `MANUAL` for steward links. An alias is born `ACTIVE`; unlinking one moves it to `UNLINKED`, after which it no longer resolves to the provider. Aliases are listed per provider with an optional `status` filter.

When the same practitioner persists as two providers, a `DataSteward` executes a merge, naming the `survivor_provider_id`, the `merged_provider_id`, a free-text `rationale`, and the `expected_provider_version` of the provider being folded in. The merge's guards evaluate in the global order of §2.6: the survivor must be `ACTIVE` for the transition to exist at all, failing as `ERR_INVALID_STATE`; then the stale-version check rejects a mismatch with `ERR_STALE_VERSION`; then the merged provider must be `ACTIVE`, failing as `ERR_PROVIDER_NOT_LINKABLE`; and finally the two parties must be distinct, failing as `ERR_MERGE_SELF` (HTTP 422). A successful merge creates a **provider merge record** — an append-only entry capturing `survivor_provider_id`, `merged_provider_id`, the deciding steward's opaque id as `decided_by_user_id`, the logical-clock instant as `decided_at`, and the `rationale` — and then rewires the duplicate's world: its attribute records re-point their `provider_id` to the survivor, with same-group overlapping intervals triggering re-resolution under the dating rules of §3.4; its aliases re-point to the survivor; its open attribute conflicts transfer to the survivor; its attestation requests in `DRAFT` or `SENT` transition to `WITHDRAWN`; quality scoring runs for the survivor; and the merged provider itself settles into the terminal `MERGED` state with `merged_into_provider_id` naming the survivor and its `version` incremented by one. Merge records may be listed with optional `survivor_provider_id` and `merged_provider_id` filters, or per provider through the provider's merge-record listing.

### 3.7. The Provider Data Quality Score

Every provider carries a quality score between 0 and 100, recomputed whenever the evidence changes: a roster file commit, a conflict resolution, an attestation response, the attestation expiry sweep, a provider merge, or an explicit steward-triggered recompute. Each computation appends a new, immutable score row — never updating history — recording the `provider_id`, the logical-clock instant as `computed_at`, the four components, the resulting `total_score`, and, when a commit triggered the computation, the responsible `roster_file_id`. The provider's `current_quality_score` is always the latest committed row's `total_score`, and 0 for a provider that has never been scored. Score history is listed per provider, while a cross-provider listing accepts optional `provider_id` and `roster_file_id` filters.

The `completeness_component` contributes up to 40 points. The required-key catalogue spans ten entries: `name`, `dob`, and `gender` in the `DEMOGRAPHIC` group; `primary_taxonomy` in `SPECIALTY`; `street1`, `city`, `state`, and `zip` in `PRACTICE_ADDRESS`; `phone` in `CONTACT`; and `license_number` and `license_state` in `LICENSE`. The component is forty points scaled by the fraction of those ten keys that hold an `ACTIVE`, non-terminated attribute, rounded half-up to a whole number — the system's single rounding step, applied only at this final multiplication per §2.10.

The `freshness_component` contributes up to 30 points, six for each of the five attribute groups that is fresh. A group is stale when the most recent `effective_date` among its `ACTIVE` attributes is earlier than the logical clock date minus the `freshness_sla_days` of the asserting attribute's source; a group holding no `ACTIVE` attributes at all counts as stale. The same comparison drives the provider's `staleness_flag`, which is set when any non-terminated attribute group's most recent asserted `effective_date` across committed rows predates the logical clock date minus its source's `freshness_sla_days`.

The `conflict_component` contributes up to 20 points, starting at 20 and forfeiting five points per unresolved conflict — counting both `OPEN` and `ESCALATED` conflicts — never dropping below zero. The `attestation_component` contributes up to 10 points, starting at 10 and forfeiting five points per consecutive unanswered outreach: the provider's attestation requests are scanned backward from the most recent `sent_at`, counting consecutive requests in `EXPIRED` or `ESCALATED` status and stopping at the first `RESPONDED` or `WITHDRAWN`, and the component never drops below zero. The `total_score` is the sum of the four components.

One scoring variant exists, and it belongs to distribution. When a score is computed to determine eligibility for a target whose `target_code` is `DIRECTORY`, each `ESCALATED` conflict forfeits ten points instead of five in the conflict component. This stricter figure is used only for that eligibility check; it never overwrites the provider's stored score.

### 3.8. Attestation Campaigns, Outreach, and Escalation

When data goes stale, the office asks providers to attest. A `DataSteward` creates an **attestation campaign** with a `name` and a `window_days` SLA of at least 1 — the number of days within which a dispatched request must be answered before it expires — and the campaign begins in `DRAFT`. Opening it moves it to `OPEN`; closing it moves it to `CLOSED`, but only while no request in the campaign remains in `SENT` or `ESCALATED` status — otherwise the close is rejected with `ERR_CAMPAIGN_HAS_OPEN_REQUESTS` (HTTP 409) — and closing withdraws any requests still in `DRAFT`.

Inside a campaign, the steward creates a request for a provider by `provider_id`; the request starts in `DRAFT`. Dispatching it moves the request `DRAFT` → `SENT`, stamps `sent_at` from the logical clock, and computes `due_at` as `sent_at` plus the campaign's `window_days` — an exclusive deadline compared against the logical clock, so a response arriving at or after `due_at` is too late. Dispatch is guarded, with the checks evaluated in this order after state legality: the provider must be `ACTIVE`, failing as `ERR_PROVIDER_NOT_LINKABLE`; the provider must not already carry another request in `SENT` or `ESCALATED` status, failing as `ERR_ATTESTATION_ALREADY_INFLIGHT` (HTTP 409); and the campaign must be `OPEN`, failing as `ERR_CAMPAIGN_NOT_OPEN` (HTTP 409). Requests are browsable within their campaign, across campaigns with optional `provider_id`, `status`, and `attestation_campaign_id` filters, or per provider.

A `ProviderContact` answers a `SENT` request by responding with an `attestation_outcome` of `CONFIRMED` or `CORRECTED`. The response must arrive while the logical clock is strictly earlier than `due_at`, or it is rejected with `ERR_ATTESTATION_WINDOW_CLOSED` (HTTP 409); this window check is evaluated before the payload check. A `CORRECTED` outcome must carry the corrections in `corrected_payload`, or the call fails with `ERR_CORRECTION_PAYLOAD_REQUIRED` (HTTP 422). A response stamps `responded_at` from the logical clock and lands the request in `RESPONDED`. Corrections write through to the attribute timeline: each field of `corrected_payload` is upserted as an attribute whose `effective_date` is the logical clock date, with provenance pointing at the attestation pseudo-source — the `roster_source_id` of the feed that names this campaign as its `default_attestation_campaign_id` when such a feed is configured, and otherwise the incumbent attribute's own source. Quality scoring re-runs, since the attestation component improves.

Requests that outlive their window are reaped by a steward-invoked sweep: every `SENT` request whose `due_at` has been reached or passed by the logical clock transitions to `EXPIRED`, each expiry triggers a recomputation of the provider's `staleness_flag` and a fresh quality-score run in which the attestation component drops, and the sweep reports the damage as `expired_count` alongside the `expired_request_ids` it touched. Expiry is not the end of the road: a steward may escalate an `EXPIRED` request to `ESCALATED`, but only within one additional window — while the logical clock remains strictly earlier than `due_at` plus `window_days` — with later attempts rejected as `ERR_ESCALATION_WINDOW_CLOSED` (HTTP 409). Escalation carries teeth: the system counts the provider's consecutive requests that reached expiry, scanning backward by `sent_at` and stopping at the first `RESPONDED` or `WITHDRAWN`, and when that count reaches two — the threshold is inclusive, so exactly the second consecutive expiry suspends — the provider's `lifecycle_status` moves `ACTIVE` → `SUSPENDED`. A `DRAFT` request may also simply be withdrawn, moving to `WITHDRAWN`; and per §3.6, provider suspension withdraws `SENT` requests while a merge withdraws both `DRAFT` and `SENT` ones. `DRAFT`, `SENT`, `RESPONDED`, `EXPIRED`, `ESCALATED`, and `WITHDRAWN` make up the request state space, with `RESPONDED`, `EXPIRED`, and `WITHDRAWN` terminal.

### 3.9. Downstream Distribution and Snapshot Publishing

The office publishes provider truth to downstream systems through **distribution targets**. A `DistributionOperator` registers a target with a `target_code` of `CLAIMS`, `DIRECTORY`, or `NETWORK`, the delivery address as `endpoint_uri`, and a `required_quality_floor` from 0 to 100 — the minimum provider quality score for inclusion in snapshots to this target. A target begins `ACTIVE` and may later be disabled, moving to `DISABLED`; targets are listed with an optional `status` filter.

Publishing proceeds by batch. Creating a batch for a target — by `distribution_target_id` — opens it in `BUILDING` with `snapshot_cutoff_at` frozen to the logical clock at creation. Optionally the creation names a `retry_of_batch_id`: when it names a `FAILED` batch, that failed batch moves to `SUPERSEDED` as the new batch opens, making the new batch its manual retry. Batches are listed with optional `distribution_target_id`, `status`, and `retry_of_batch_id` filters.

Publishing a `BUILDING` batch freezes its item set as of `snapshot_cutoff_at` and moves it to `PUBLISHED`. Two guards apply, evaluated in this order after state legality: no other batch for the same target may stand in `BUILDING` or `PUBLISHED`, failing as `ERR_BATCH_INFLIGHT` (HTTP 409); and the target must be `ACTIVE`, failing as `ERR_TARGET_DISABLED` (HTTP 409). Snapshot selection then decides the contents. A provider is eligible when its `lifecycle_status` is `ACTIVE` at the cutoff and its score meets the target's `required_quality_floor` — the plain `current_quality_score` for `CLAIMS` and `NETWORK` targets, and the stricter directory variant of §3.7, in which escalated conflicts cost double, for `DIRECTORY` targets. Each provider's change is classified against the target's most recent `ACKED` batch, the baseline: a provider absent from the baseline appears as `ADD`; one present whose `payload_hash` has changed appears as `UPDATE`; one present who has since become `TERMINATED` or `MERGED` appears as `TERM`; and one present whose score has dropped below the floor appears as `QUALITY_DROP_EXCLUDED`. Each classification materializes a **distribution item** recording the `distribution_batch_id`, the `provider_id`, the `change_kind`, and the `payload_hash` of the provider payload slice sent — an append-only record carrying only `id` and `created_at`, per §2.5. Items are ordered inside the snapshot first by change-kind rank — `ADD`, then `UPDATE`, then `TERM`, then `QUALITY_DROP_EXCLUDED` — then by provider `npi` ascending, then by provider `created_at` ascending, never by `id`; and the batch's `provider_count` records how many items were materialized. Items may be browsed within their batch, or across batches for a given provider, with an optional `change_kind` filter in both listings.

A published batch awaits its downstream fate. Acknowledgement moves it `PUBLISHED` → `ACKED`, making it the new baseline for future snapshots. Failure moves it `PUBLISHED` → `FAILED` and requires a `failure_reason` in the request. A batch still `BUILDING` may be discarded, moving to `SUPERSEDED`; `ACKED` and `SUPERSEDED` are the terminal batch states.

## 4. Endpoint Definitions

Operations that create new resources return a `201 Created` status code: registering a roster source, registering a roster file, manually creating a provider, manually adding an attribute, registering a distribution target, creating a distribution batch, creating an attestation campaign, creating an attestation request, and executing a provider merge (which creates the merge record). All other operations — reads, patches, and state-transition actions, including setting the logical clock — return a `200 OK` status code. Complete request and response shapes are defined by the workflows of §3; this table is a summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/pdm/_clock/set_current_utc` | Set the server logical clock | DataSteward |
| POST | `/pdm/roster-sources` | Register an upstream roster feed | DataSteward |
| GET | `/pdm/roster-sources` | List roster sources with pagination and optional filters | DataSteward, IntakeOperator, DistributionOperator, ProviderContact |
| GET | `/pdm/roster-sources/{id}` | Get one roster source | DataSteward, IntakeOperator, DistributionOperator |
| PATCH | `/pdm/roster-sources/{id}` | Update mutable roster source fields | DataSteward |
| POST | `/pdm/roster-sources/{id}/suspend` | Suspend a source (blocked with inflight files) | DataSteward |
| POST | `/pdm/roster-sources/{id}/resume` | Resume a suspended source | DataSteward |
| POST | `/pdm/roster-sources/{id}/retire` | Retire a source | DataSteward |
| POST | `/pdm/roster-files` | Register an inbound roster file | IntakeOperator |
| GET | `/pdm/roster-files` | List roster files | DataSteward, IntakeOperator |
| GET | `/pdm/roster-files/{id}` | Get one roster file | DataSteward, IntakeOperator |
| POST | `/pdm/roster-files/{id}/parse` | Parse file into roster rows | IntakeOperator |
| POST | `/pdm/roster-files/{id}/normalize` | Normalize parsed rows; malformed rows reject with reasons | IntakeOperator |
| POST | `/pdm/roster-files/{id}/validate` | Run identity resolution over normalized rows | IntakeOperator |
| POST | `/pdm/roster-files/{id}/commit` | Commit a validated file; OCC-guarded; SoD-checked | IntakeOperator |
| POST | `/pdm/roster-files/{id}/reject` | Reject a file pre-commit | IntakeOperator |
| POST | `/pdm/roster-files/{id}/supersede` | Mark a committed file superseded by a replacement | DataSteward |
| GET | `/pdm/roster-files/{id}/roster-rows` | List rows of a file | DataSteward, IntakeOperator |
| GET | `/pdm/roster-rows/{id}` | Get one roster row | DataSteward, IntakeOperator |
| GET | `/pdm/roster-rows` | List roster rows across files with optional filters | DataSteward, IntakeOperator |
| POST | `/pdm/roster-rows/{id}/link` | Manually link a PENDING or CONFLICT row to an ACTIVE provider | DataSteward |
| POST | `/pdm/roster-rows/{id}/spawn-new` | Resolve a CONFLICT row by declaring it a new provider | DataSteward |
| POST | `/pdm/roster-rows/{id}/reject` | Manually reject a PENDING row | IntakeOperator |
| POST | `/pdm/providers` | Manually create a provider | DataSteward |
| GET | `/pdm/providers` | List providers with filters and pagination | DataSteward, IntakeOperator, DistributionOperator, ProviderContact |
| GET | `/pdm/providers/{id}` | Get one provider | DataSteward, IntakeOperator, DistributionOperator, ProviderContact |
| POST | `/pdm/providers/{id}/suspend` | Suspend a provider | DataSteward |
| POST | `/pdm/providers/{id}/reinstate` | Reinstate a suspended provider (quality floor gate) | DataSteward |
| POST | `/pdm/providers/{id}/terminate` | Terminate a provider; open-ended attributes term-dated | DataSteward |
| POST | `/pdm/providers/{id}/attributes` | Manually add an effective-dated attribute to a provider | DataSteward |
| GET | `/pdm/providers/{id}/attributes` | List attributes of a provider | DataSteward, IntakeOperator, DistributionOperator |
| GET | `/pdm/provider-attributes/{id}` | Get one attribute | DataSteward, IntakeOperator |
| GET | `/pdm/provider-attributes` | List attributes across providers with optional provenance filters | DataSteward, IntakeOperator |
| PATCH | `/pdm/provider-attributes/{id}` | Correct an attribute value or term date (re-runs interval logic) | DataSteward |
| POST | `/pdm/provider-attributes/{id}/approve-retro` | Approve a RETRO_PENDING attribute; OCC on provider | DataSteward |
| POST | `/pdm/provider-attributes/{id}/void` | Void a RETRO_PENDING attribute | DataSteward |
| GET | `/pdm/providers/{id}/aliases` | List aliases of a provider | DataSteward, IntakeOperator |
| POST | `/pdm/provider-aliases/{id}/unlink` | Unlink an alias (it will no longer resolve to the provider) | DataSteward |
| GET | `/pdm/attribute-conflicts` | List conflicts with filters | DataSteward |
| GET | `/pdm/attribute-conflicts/{id}` | Get one conflict | DataSteward |
| POST | `/pdm/attribute-conflicts/{id}/resolve` | Resolve a conflict (KEEP_INCUMBENT, ACCEPT_CHALLENGER, MERGE_VALUES); SoD-checked | DataSteward |
| POST | `/pdm/attribute-conflicts/{id}/escalate` | Escalate a conflict (blocked on precedence ties) | DataSteward |
| POST | `/pdm/distribution-targets` | Register a downstream target | DistributionOperator |
| GET | `/pdm/distribution-targets` | List targets | DataSteward, DistributionOperator |
| POST | `/pdm/distribution-targets/{id}/disable` | Disable a target | DistributionOperator |
| POST | `/pdm/distribution-batches` | Create a batch for a target (optionally a retry of a FAILED batch) | DistributionOperator |
| GET | `/pdm/distribution-batches` | List batches | DataSteward, DistributionOperator |
| GET | `/pdm/distribution-batches/{id}` | Get one batch | DataSteward, DistributionOperator |
| GET | `/pdm/distribution-batches/{id}/items` | List items of a batch | DataSteward, DistributionOperator |
| GET | `/pdm/providers/{id}/distribution-items` | List distribution items across batches that reference a provider | DataSteward, DistributionOperator |
| POST | `/pdm/distribution-batches/{id}/publish` | Publish a BUILDING batch; freezes the item set | DistributionOperator |
| POST | `/pdm/distribution-batches/{id}/ack` | Mark a published batch acknowledged by the downstream | DistributionOperator |
| POST | `/pdm/distribution-batches/{id}/fail` | Mark a published batch failed | DistributionOperator |
| POST | `/pdm/distribution-batches/{id}/discard` | Discard a BUILDING batch | DistributionOperator |
| POST | `/pdm/attestation-campaigns` | Create a campaign | DataSteward |
| GET | `/pdm/attestation-campaigns` | List campaigns | DataSteward, ProviderContact |
| GET | `/pdm/attestation-campaigns/{id}` | Get one campaign | DataSteward, ProviderContact |
| POST | `/pdm/attestation-campaigns/{id}/open` | Open a campaign | DataSteward |
| POST | `/pdm/attestation-campaigns/{id}/close` | Close a campaign (blocked with open requests) | DataSteward |
| POST | `/pdm/attestation-campaigns/{id}/attestation-requests` | Create a DRAFT attestation request for a provider inside a campaign | DataSteward |
| GET | `/pdm/attestation-campaigns/{id}/attestation-requests` | List requests in a campaign | DataSteward, ProviderContact |
| GET | `/pdm/attestation-requests` | List requests across campaigns | DataSteward, ProviderContact |
| GET | `/pdm/attestation-requests/{id}` | Get one attestation request | DataSteward, ProviderContact |
| GET | `/pdm/providers/{id}/attestation-requests` | List attestation requests for a provider | DataSteward, ProviderContact |
| POST | `/pdm/attestation-requests/{id}/send` | Dispatch a DRAFT request; starts the SLA window | DataSteward |
| POST | `/pdm/attestation-requests/{id}/respond` | Provider contact responds CONFIRMED or CORRECTED | ProviderContact |
| POST | `/pdm/attestation-requests/{id}/escalate` | Escalate an EXPIRED request within the escalation window | DataSteward |
| POST | `/pdm/attestation-requests/{id}/withdraw` | Withdraw a DRAFT request | DataSteward |
| POST | `/pdm/attestation-requests/sweep` | System sweep: all SENT requests at or past their deadline expire | DataSteward |
| GET | `/pdm/providers/{id}/quality-scores` | List score history for a provider | DataSteward, IntakeOperator, DistributionOperator |
| POST | `/pdm/providers/{id}/quality-scores/recompute` | Force recompute of a provider's quality score | DataSteward |
| GET | `/pdm/quality-scores` | List quality score rows across providers | DataSteward, IntakeOperator, DistributionOperator |
| GET | `/pdm/quality-scores/{id}` | Get one quality score row | DataSteward, IntakeOperator, DistributionOperator |
| POST | `/pdm/provider-merges` | Merge a duplicate provider into a survivor; OCC on merged provider | DataSteward |
| GET | `/pdm/provider-merges` | List merge records | DataSteward |
| GET | `/pdm/provider-merges/{id}` | Get one merge record | DataSteward |
| GET | `/pdm/providers/{id}/merge-records` | List merge records where this provider is survivor or merged party | DataSteward |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this table is an index only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_SOD_SAME_USER` | 403 Forbidden |
| `ERR_SOD_ADJUDICATOR` | 403 Forbidden |
| `ERR_SOURCE_NOT_ACTIVE` | 409 Conflict |
| `ERR_PRECEDENCE_RANK_CONFLICT` | 409 Conflict |
| `ERR_DUPLICATE_FILE` | 409 Conflict |
| `ERR_ROW_COUNT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_UNRESOLVED_ROW_CONFLICTS` | 409 Conflict |
| `ERR_INVALID_DATE_RANGE` | 422 Unprocessable Entity |
| `ERR_PROVIDER_NOT_LINKABLE` | 409 Conflict |
| `ERR_MERGE_SELF` | 422 Unprocessable Entity |
| `ERR_QUALITY_FLOOR_NOT_MET` | 409 Conflict |
| `ERR_BATCH_INFLIGHT` | 409 Conflict |
| `ERR_TARGET_DISABLED` | 409 Conflict |
| `ERR_ATTESTATION_ALREADY_INFLIGHT` | 409 Conflict |
| `ERR_CAMPAIGN_NOT_OPEN` | 409 Conflict |
| `ERR_CAMPAIGN_HAS_OPEN_REQUESTS` | 409 Conflict |
| `ERR_OPEN_ATTESTATION_EXISTS` | 409 Conflict |
| `ERR_MERGE_VALUE_REQUIRED` | 422 Unprocessable Entity |
| `ERR_PRECEDENCE_TIE_NOT_ESCALATABLE` | 409 Conflict |
| `ERR_NO_REPLACEMENT_FILE` | 409 Conflict |
| `ERR_SOURCE_HAS_INFLIGHT_FILE` | 409 Conflict |
| `ERR_ATTESTATION_WINDOW_CLOSED` | 409 Conflict |
| `ERR_ESCALATION_WINDOW_CLOSED` | 409 Conflict |
| `ERR_CORRECTION_PAYLOAD_REQUIRED` | 422 Unprocessable Entity |
