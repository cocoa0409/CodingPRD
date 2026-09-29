# Public Art Conservation API — Product Requirements Document

## 1. Introduction

A municipal public art collection is a set of objects that cannot be moved into a climate-controlled vault when the weather turns. Bronzes oxidise on the waterfront, painted steel chalks under sun, murals are tagged on Friday nights, and every one of those works carries a legal relationship with a living artist or an artist's estate that survives the acquisition agreement. The city's registrars, surveyors and conservators currently reconcile all of this across spreadsheets, e-mail threads and a shared drive of photographs, which means nobody can answer the two questions the arts commission asks every budget cycle: which works are deteriorating fastest, and can we afford to treat them.

This document specifies the Public Art Conservation API, the system of record for that collection. It governs the accession register (works, artists, installation sites and acquisition documentation), the recurring condition-survey cycle with its photographic documentation requirement and treatment-priority ranking, routine material care protocols covering washing, waxing, coating renewal and graffiti removal, the engagement of outside conservators through costed treatment proposals, the moral-rights and artist-consultation obligations that gate any alteration, relocation or removal, the deaccession review process with its public comment period and commission ballot, the maintenance endowments and percent-for-art set-asides that pay for all of it, and the vandalism and damage response track with its insurance claims.

Two design commitments run through the whole specification. First, **segregation of duties**: the person who performs a survey is not the person who signs it off, and the person who initiates a deaccession is not permitted to vote it through. Second, **traceable consequence**: a single decision — finalizing a survey, approving a proposal, executing a deaccession — is allowed to reach across the register and change works, visits, proposals, notices, consultations and money, but every one of those secondary movements is specified here rather than left to implementation taste. The API is mounted under `/public-art`, with a single test-driving clock endpoint outside that mount.

## 2. Global Specifications & System-Wide Principles

This section defines the contract-level rules that hold everywhere: authentication, response shape, pagination, common record properties, the logical clock, evaluation ordering, precision, and concurrency protection.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If either header is absent, empty or whitespace-only, or if `X-User-Role` is not one of the nine roles below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are well formed but the declared role is not among those authorized for the endpoint being called, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The nine roles are:

- `CollectionsRegistrar` — accessions works, maintains inventory and location records, reports damage.
- `ConditionSurveyor` — performs condition surveys and attaches photographic documentation; may submit a survey but never finalize one.
- `ChiefConservator` — reviews and finalizes surveys, drafts treatment proposals, triages damage; cannot approve proposals or move money.
- `ConservatorVendor` — the engaged conservation firm, executing approved treatments on its own proposals only.
- `MaintenanceCrew` — performs routine care visits, including cleaning, waxing and graffiti removal.
- `PublicArtManager` — programme manager; approves treatments, runs the deaccession process and the cycle checkpoint.
- `FinanceOfficer` — opens funding pools, reserves and releases allocations, files and resolves insurance claims.
- `ArtCommissionMember` — arts commission member; casts deaccession ballots.
- `ArtistRepresentative` — the artist or their estate; responds to consultations and acknowledges moral-rights notices for their own works only.

Two of these roles are backed by a persisted entity, and for them `X-User-ID` is an entity identifier rather than a bare operator name. When `X-User-Role` is `ArtistRepresentative`, `X-User-ID` is the `id` of the acting `Artist`; ownership checks on any resource that references an `Artist` compare the resource's `artist_id` to `X-User-ID`. When `X-User-Role` is `ConservatorVendor`, `X-User-ID` is the `id` of the acting `Conservator`; ownership checks on any resource that references a `Conservator` compare the resource's `conservator_id` to `X-User-ID`. A mismatch on either is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

The remaining seven roles — `CollectionsRegistrar`, `ConditionSurveyor`, `ChiefConservator`, `MaintenanceCrew`, `PublicArtManager`, `FinanceOfficer` and `ArtCommissionMember` — carry an opaque operator identifier in `X-User-ID` that is not tied to any persisted entity. The server records it where a transition writes it down (as `submitted_by_user_id` and `finalized_by_user_id` on a condition survey, as `submitted_by_user_id` and `approved_by_user_id` on a treatment proposal, as `initiated_by_user_id` on a deaccession case, and as `member_user_id` inside a ballot record) but never compares it to any entity's `id`.

Read access is broad and write access is narrow. All nine roles may read artists, sites, artworks, protocols, conservators, condition surveys, maintenance visits, treatment proposals, consultations, notices, deaccession cases and damage incidents. Funding pools and funding allocations are the exception: only `FinanceOfficer`, `PublicArtManager` and `ChiefConservator` may read them, and any other role attempting a funding read receives `ERR_UNAUTHORIZED`.

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
- Two identifiers outside the catalogue of §5 cover transport-level failures in the same envelope: a path that matches no route answers `ERR_NOT_FOUND` (HTTP 404), and an unsupported method on a known path answers `ERR_METHOD_NOT_ALLOWED` (HTTP 405).

---

### 2.3. Pagination

List endpoints are paginated through two query parameters. `limit` caps the number of records returned; it defaults to 10, may not be smaller than 1, and may not be larger than 100. `offset` is the number of records skipped before the page begins and defaults to 0. A `limit` or `offset` that is not an integer, a `limit` outside 1 to 100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST`; query parameters an endpoint does not name — including misspelt filters — are ignored rather than rejected.

Unless a specific endpoint states otherwise, list results are ordered by `created_at` ascending, with records sharing a `created_at` — a routine outcome under a clock that does not advance on its own — ordered by insertion sequence.

Every list response echoes `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope.

### 2.4. Register Reads and Reverse Lookups

Because the register is a flat set of peer records joined by identifiers carried in request bodies, list endpoints are the only way to walk a relationship backwards, and each list therefore accepts filters matching the identifiers and classifications that point at it. Artist listings filter on `is_living`. Site listings filter on `exposure_class`. Artwork listings filter on `artist_id`, `site_id`, `material_class`, `custody_status`, `conservation_status` and `priority_basis`. Maintenance protocol listings filter on `material_class` and `method`. Conservator listings filter on `status` and on `material_specialty`, the singular form used to test membership in a conservator's declared specialties.

Condition survey listings filter on `artwork_id`, `cycle_year`, `status` and `recommendation`. Maintenance visit listings filter on `artwork_id`, `protocol_id`, `status` and `abort_reason`. Treatment proposal listings filter on `artwork_id`, `conservator_id`, `assessment_id`, `status` and `withdraw_reason`. Artist consultation listings filter on `artwork_id`, `artist_id`, `proposal_id`, `subject` and `status`. Moral-rights notice listings filter on `artwork_id`, `artist_id`, `action_type` and `status`. Deaccession case listings filter on `artwork_id`, `status` and `disposition`. Funding pool listings filter on `pool_type` and `fiscal_year`. Funding allocation listings filter on `pool_id`, `proposal_id`, `visit_id`, `purpose`, `status` and `release_reason`. Damage incident listings filter on `artwork_id`, `linked_proposal_id`, `credited_pool_id`, `incident_type`, `damage_status`, `claim_status`, `triage_class` and `claim_basis`. Every filter is optional, and filters combine conjunctively. The integer-valued filters `cycle_year` and `fiscal_year` and the boolean `is_living` are parsed from their query strings and draw `ERR_INVALID_REQUEST` when unparseable, `is_living` accepting `true`, `false`, `1` and `0`; all other filters compare as exact strings.

### 2.5. Common Record Properties

Every record in the system — artists, sites, artworks, maintenance protocols, maintenance visits, condition assessments, conservators, treatment proposals, artist consultations, moral-rights notices, deaccession cases, funding pools, funding allocations and damage incidents — carries the same four system-managed properties:

- `id` (string): a server-minted UUID. It carries no type prefix and no embedded meaning.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, stamped when the record is first stored.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the record.
- `version` (integer): a counter that increments by exactly one on every mutation of the record.

A mutation for these purposes includes any change the server makes on its own initiative, not only changes a client requested directly. When finalizing a survey rewrites an artwork's `condition_index`, when a cascade aborts a scheduled visit, when a released allocation raises a pool's `available_cents`, or when a computed roll-up such as `artwork_count`, `installed_units_used`, `open_notice_count` or `active_engagement_count` is recomputed, the affected record's `updated_at` is refreshed and its `version` is incremented. There is no entity in this system that omits `updated_at` or `version`.

Two qualifications keep that counter predictable. A recomputation that leaves a computed value — a roll-up count, a pool's `available_cents`, a work's `treatment_priority_rank` — exactly as it already stood is not a mutation of that record: its `updated_at` and `version` are left alone. And within a single request a record's `version` rises by at most one however many movements land on it: several fields rewritten by one operation, a roll-up recomputed after a direct write to the same record, and the same record touched on more than one cascade hop all count once between them, while a record the request itself created stays at `version` 1.

### 2.6. The Logical Conservation Clock

Nothing in this system reads the machine's wall clock. Every stamped instant, every deadline and every year comparison is derived from a single logical clock, which reads exactly `2026-08-01T00:00:00Z` until it is moved. An administrative test-driving capability accepts a `to_iso8601` instant and moves the clock to it, returning the new value as `current_utc`; the capability is restricted to `PublicArtManager`. The instant may lie before the clock's current value — no monotonicity is required — and the response carries `current_utc` alone.

Fields stamped from the logical clock include `sent_on`, `due_at`, `sent_at`, `earliest_action_at`, `started_at`, `completed_at`, `reported_at`, `executed_at`, `acknowledged_at`, `responded_at`, `released_at`, `public_comment_opens_on` and `public_comment_closes_at`. Where a field is an ISO date rather than an instant — `sent_on`, `public_comment_opens_on`, `last_maintenance_completed_on`, `next_maintenance_due_on` — it is the calendar date of the logical clock in UTC. Year-scoped counters such as `maintenance_applications_ytd` compare against the logical clock's year, never the current calendar year.

### 2.7. Two Independent Status Dimensions

Two records in this system track two orthogonal lifecycles on a single row, and conflating them is the most common modelling mistake. An `Artwork` carries `custody_status`, describing where the object physically is (`ON_VIEW`, `IN_STORAGE`, `IN_TREATMENT`, `DEACCESSIONED` or `DESTROYED`), and separately `conservation_status`, describing its conservation standing (`MONITORED`, `TREATMENT_REQUIRED`, `TREATMENT_IN_PROGRESS` or `STABILIZED`). A newly accessioned work begins `ON_VIEW` and `MONITORED`. `DEACCESSIONED` and `DESTROYED` are terminal for the custody dimension; the conservation dimension is deliberately cyclic and has no terminal value.

A `DamageIncident` behaves the same way. Its `damage_status` follows the physical response route (`REPORTED`, `TRIAGED`, `RESOLVED`) while its `claim_status` follows the insurance track (`NONE`, `FILED`, `SETTLED`, `DENIED`). An incident may be resolved without a claim ever being filed, and a claim may settle while the damage is still being repaired. When a requested move is not declared for the current value of the dimension it targets, the rejection names the dimension: `ERR_INCIDENT_INVALID_STATE` for the damage dimension and `ERR_CLAIM_INVALID_STATE` for the insurance dimension.

### 2.8. Order of Evaluation

Many operations are guarded by several checks at once, and the order in which they fire is part of the contract, because it determines which error a client sees. Checks are evaluated in the following sequence, and the first one that fails ends the request:

1. Header presence and role validity — `ERR_UNAUTHENTICATED`.
2. Role authorization for the called endpoint — `ERR_UNAUTHORIZED`.
3. Resolution of every identifier appearing in the URL path, left to right, each against its own store, returning that entity's own code: `ERR_ARTWORK_NOT_FOUND`, `ERR_ARTIST_NOT_FOUND`, `ERR_SITE_NOT_FOUND`, `ERR_PROTOCOL_NOT_FOUND`, `ERR_VISIT_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_CONSERVATOR_NOT_FOUND`, `ERR_PROPOSAL_NOT_FOUND`, `ERR_CONSULTATION_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_POOL_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND` or `ERR_INCIDENT_NOT_FOUND`.
4. Request-body shape on every write: all required fields present, no unknown fields, every enum member drawn from its declared set, every number inside its declared range, `window_end` strictly after `window_start`, `engagement_end` strictly after `engagement_start`, `damage_extent_pct` between 0.00 and 1.00 inclusive, and `criteria` carrying at least one member — otherwise `ERR_INVALID_REQUEST`. An absent or empty body reads as an empty object; a body that is not a JSON object — malformed JSON, or a JSON array, string or number — is itself an `ERR_INVALID_REQUEST`; and an explicit null counts as absence, so it fails a required field and takes the declared default on an optional one.
5. Resolution of every foreign identifier carried in the request body, again returning the referenced entity's own not-found code from the same list — `ERR_ARTIST_NOT_FOUND` when an `artist_id` in a body names no artist, `ERR_SITE_NOT_FOUND` for a `site_id` or a `to_site_id`, `ERR_ARTWORK_NOT_FOUND` for an `artwork_id`, `ERR_PROTOCOL_NOT_FOUND` for a `protocol_id`, `ERR_ASSESSMENT_NOT_FOUND` for an `assessment_id`, `ERR_CONSERVATOR_NOT_FOUND` for a `conservator_id`, `ERR_PROPOSAL_NOT_FOUND` for a `proposal_id` or a `linked_proposal_id`, `ERR_VISIT_NOT_FOUND` for a `visit_id`, and `ERR_POOL_NOT_FOUND` for a `pool_id` or a `credited_pool_id`.
6. On drafting a treatment proposal, agreement between `expected_artwork_version` and the artwork's current `version` — `ERR_STALE_ARTWORK_VERSION`.
7. On reserving a funding allocation, agreement between `expected_pool_version` and the pool's current `version` — `ERR_STALE_POOL_VERSION`.
8. Ownership for the two entity-backed roles — `ERR_NOT_RESOURCE_OWNER`. This applies to exactly four operations: an artist responding to a consultation, an artist acknowledging a notice, a conservator starting execution of a treatment, and a conservator completing a treatment.
9. The state precondition of the requested transition, returning the target entity's own code: `ERR_ASSESSMENT_INVALID_STATE`, `ERR_PROPOSAL_INVALID_STATE`, `ERR_VISIT_INVALID_STATE`, `ERR_CASE_INVALID_STATE`, `ERR_NOTICE_INVALID_STATE`, `ERR_CONSULTATION_INVALID_STATE`, `ERR_ALLOCATION_INVALID_STATE`, `ERR_INCIDENT_INVALID_STATE` or `ERR_CLAIM_INVALID_STATE`.
10. Segregation of duties on survey finalization — `ERR_SEGREGATION_OF_DUTIES`.
11. Segregation of duties on deaccession balloting — `ERR_INITIATOR_CANNOT_VOTE`.
12. The referenced artwork is not already out of the collection — `ERR_ARTWORK_DEACCESSIONED`. This guards every write that names an `artwork_id` in its path or its body — relocating a work, opening a condition survey, scheduling a maintenance visit, drafting a treatment proposal, opening an artist consultation, sending a moral-rights notice, opening a deaccession case and reporting a damage incident — together with those transitions of a survey, a visit, a proposal or a deaccession case that act on the work itself: survey submission (on the first pass only, per §3.2) and finalization, starting and completing a maintenance visit, proposal submission (on the first pass only, per §3.4), approval, start of execution and completion, and the first advance (per §3.8) and the execution of a deaccession case. The remaining writes do not consult it: appending a photograph, a cost line or a ballot, requesting a revision on a survey or a proposal, rejecting a proposal, responding to a consultation, acknowledging a notice, triaging an incident, filing or resolving a claim, and reserving or releasing funding.
13. The referenced artwork's custody permits the operation — `ERR_ARTWORK_CUSTODY_INVALID`. This guards exactly three operations: starting a maintenance visit, starting a treatment execution, and relocating a work.
14. Protection of works of recognized stature from destruction — `ERR_RECOGNIZED_STATURE_PROTECTED`.
15. Existence of a required artist consultation — `ERR_ARTIST_CONSULTATION_REQUIRED`.
16. That consultation not being unanswered — `ERR_ARTIST_CONSULTATION_PENDING`.
17. That consultation not being an objection — `ERR_ARTIST_OBJECTION_UNRESOLVED`.
18. Existence of a matching moral-rights notice — `ERR_MORAL_RIGHTS_NOTICE_REQUIRED`.
19. Maturity of that notice's waiting period — `ERR_MORAL_RIGHTS_WAIT_ACTIVE`.
20. Conservator eligibility — `ERR_CONSERVATOR_NOT_ELIGIBLE`.
21. Protocol and artwork material agreement — `ERR_PROTOCOL_MATERIAL_MISMATCH`.
22. Photographic documentation sufficiency — `ERR_PHOTO_DOCUMENTATION_INSUFFICIENT`.
23. A scheduled work window not lying in the past — `ERR_WINDOW_IN_PAST`.
24. A visit's window having opened — `ERR_VISIT_WINDOW_NOT_OPEN`.
25. A public comment period having closed — `ERR_PUBLIC_COMMENT_OPEN`.
26. A consultation response arriving in time — `ERR_CONSULTATION_WINDOW_CLOSED`.
27. Uniqueness of `accession_number`, `site_code`, `protocol_code` and `pool_code`, each within its own record type — `ERR_DUPLICATE_CODE`.
28. Conservator engagement-window exclusivity — `ERR_CONSERVATOR_WINDOW_CONFLICT`.
29. Site concurrent-work capacity — `ERR_SITE_WORK_CAPACITY_CONFLICT`.
30. Site installed-footprint capacity — `ERR_SITE_CAPACITY_EXCEEDED`. This guards both accessioning a work and relocating one.
31. One live proposal per survey — `ERR_DUPLICATE_ACTIVE_PROPOSAL`.
32. The cited survey being finalized and belonging to the same work — `ERR_ASSESSMENT_NOT_FINALIZED`.
33. The protocol's annual application ceiling — `ERR_MAX_ANNUAL_APPLICATIONS`.
34. One ballot per commission member per case — `ERR_DUPLICATE_BALLOT`.
35. The revision-round ceiling, on both survey revision requests and proposal revision requests — `ERR_REVISION_LIMIT_REACHED`.
36. A disposition target being named where one is required — `ERR_DISPOSITION_TARGET_REQUIRED`.
37. Allocation link consistency — `ERR_ALLOCATION_LINK_MISMATCH`.
38. Claim-basis support — `ERR_CLAIM_BASIS_UNSUPPORTED`.
39. A pool named to receive a settlement — `ERR_CREDIT_POOL_REQUIRED`.
40. Sufficient pool availability at reservation time — `ERR_POOL_FUNDS_INSUFFICIENT`.
41. Reserved funding covering an estimate at approval time — `ERR_FUNDING_NOT_RESERVED`.
42. A non-zero payable settlement — `ERR_NO_SETTLEMENT_PAYABLE`.

The practical consequence of this ordering is worth stating plainly: a work that has already left the collection surfaces as `ERR_ARTWORK_DEACCESSIONED` before any material, funding or scheduling rule is consulted, and a stale version on a proposal draft surfaces before the artwork's custody is even inspected.

### 2.9. Cascade Discipline

Three named cascades run in this system, and each is specified as an ordered chain of hops so that a reader can reconstruct exactly what changed and why.

**Cascade A** begins when a condition survey is finalized. Hop 1 supersedes the artwork's previously finalized surveys. Hop 2 rewrites the artwork's condition and priority fields and may move its conservation dimension. Hop 3 aborts the scheduled routine visits that the new treatment requirement has made pointless. Hop 4 releases the funding those aborted visits were holding. Hop 5 recomputes the affected pool's availability upward by the released amounts.

**Cascade B** begins when an approved deaccession case is executed. Hop 1 moves the artwork's custody to its terminal value and returns its footprint to the site. Hop 2 terminates everything still hanging off that artwork: non-terminal treatment proposals, scheduled maintenance visits, pending artist consultations, and open moral-rights notices other than the one the execution consumed. Hop 3 releases the funding held by those terminated proposals and visits. Hop 4 recomputes the affected pools' availability upward.

**Cascade C** begins when a treatment proposal is approved. Hop 1 withdraws the artwork's other non-terminal proposals as superseded. Hop 2 releases the funding those superseded proposals were holding. Hop 3 recomputes pool availability upward.

Every record touched by any hop of any cascade has its `updated_at` refreshed and its `version` incremented, exactly as if a client had written to it directly. Cascades are applied immediately and synchronously within the request that triggered them; there is no deferred or eventual reconciliation anywhere in this system.

### 2.10. Precision, Rounding and Money

All monetary quantities are integers denominated in cents; there are no fractional cents anywhere in a stored record or an API response. Wherever a monetary computation produces a fraction, it is rounded half up to a whole cent. Where a specification says that rounding happens per line and then the rounded lines are summed, that order is normative and is not interchangeable with summing raw products and rounding once — the two differ by a cent whenever a line's labour lands on a half cent.

Two scores are not monetary. A condition index is carried to exactly one decimal place, rounded half up, and is floored at 0.0. A treatment priority score is carried to exactly two decimal places, rounded half up, with the rounding applied once to the final product rather than to any intermediate factor. Basis-point rates are converted by dividing by 10,000; percentages expressed as decimals are applied directly.

### 2.11. Guarding Against Stale Reads

Two write operations require the client to prove it has seen the current state of a parent record before it may act, because both parents are routinely moved by cascades that no client requested.

Drafting a treatment proposal must carry `expected_artwork_version`, a non-optional field holding the `version` of the target `Artwork` as the client last observed it. If that value does not equal the artwork's current `version`, the draft is rejected with `ERR_STALE_ARTWORK_VERSION` (HTTP 412). This matters because approving one proposal legitimately withdraws the artwork's other non-terminal proposals, so a writer working from an outdated view of the work must re-read it before drafting rather than adding a proposal to a contest it has already lost.

Reserving a funding allocation must carry `expected_pool_version`, a non-optional field holding the `version` of the target `FundingPool` as the client last observed it. If that value does not equal the pool's current `version`, the reservation is rejected with `ERR_STALE_POOL_VERSION` (HTTP 412). Cascaded releases and insurance credits change a pool's `available_cents` without any request touching the allocation, so a reservation carrying an outdated pool version is refused rather than charged against a balance the client never saw.

No other endpoint in this system takes a version field, and no other endpoint performs a version comparison.

## 3. Business Logic & Workflows

### 3.1. Building the Register: Artists, Sites and Accessioned Works

The register begins with the people. A `CollectionsRegistrar` or a `PublicArtManager` registers an artist of record by supplying `full_name`, the boolean `is_living` and a `contact_email` that serves as the notification address of record. Where the artist has died, `deceased_on` carries the ISO date of death and is required; where `is_living` is true, `deceased_on` must be null, and violating either direction of that pairing is a shape failure. An estate or gallery may be named in `represented_by`, which otherwise stays null. Three further optional inputs establish the artist's procedural terms: `moral_rights_waiver_on_file` records whether a signed waiver has been filed and defaults to false; `notice_wait_days` sets the mandatory waiting period between sending a moral-rights notice and acting on it, defaulting to 90 days and accepted anywhere from 1 to 365; and `consultation_response_days` sets how long the artist has to answer a consultation before it lapses, defaulting to 30 days and accepted anywhere from 1 to 180. Each artist also carries a read-only `artwork_count`, initialised to zero and maintained as the number of `Artwork` rows attributing them, counted regardless of those works' custody.

Installation sites are registered by the same two roles. A site is defined by a `site_code` unique across all sites, a human-readable `name`, an `address_ref` giving the municipal address or parcel reference, and an `exposure_class` drawn from `COASTAL`, `URBAN`, `PARK` and `INTERIOR`. Two capacity numbers govern what the site can hold: `capacity_units`, the maximum installed footprint the site can accommodate, which may be zero but never negative, and `concurrent_work_capacity`, the maximum number of maintenance work windows that may overlap there, which defaults to 1 and must be at least 1. The site's read-only `installed_units_used` starts at zero and is maintained as the sum of `footprint_units` over the works whose `site_id` names this site and whose `custody_status` is either `ON_VIEW` or `IN_TREATMENT` — a work under treatment still occupies its plinth, so it still consumes footprint, while a work in storage does not.

Accessioning is the `CollectionsRegistrar`'s exclusive act. The payload names the work's `accession_number`, which must be unique across the collection and otherwise draws `ERR_DUPLICATE_CODE`, its `title`, the `artist_id` of the attributed artist and the `site_id` where it is being installed, together with an `acquisition_date` and an `acquisition_document_ref` pointing at the acquisition agreement on file. Three classifications drive later behaviour: `material_class`, one of `BRONZE`, `PAINTED_STEEL`, `STONE` or `MURAL_COATING`, which selects condition weights, permissible care protocols and the graffiti response window; `significance_tier`, one of `LANDMARK`, `SIGNIFICANT` or `STANDARD`, which multiplies the treatment priority; and the optional `recognized_stature` boolean, defaulting to false, which permanently bars the work from destruction. The work's `footprint_units`, a required integer of at least 1, is what it consumes at the site, and accessioning is refused with `ERR_SITE_CAPACITY_EXCEEDED` when the site's existing `installed_units_used` plus this work's `footprint_units` would exceed the site's `capacity_units`. A required `insured_value_cents` of zero or more schedules the work for insurance purposes.

A successful accession sets `custody_status` to `ON_VIEW` and `conservation_status` to `MONITORED`, raises the site's `installed_units_used` by the work's `footprint_units`, and raises the attributed artist's `artwork_count` by one. It also derives `moral_rights_status`, the field that governs every later consent obligation: the value is `WAIVED` when the attributed artist has `moral_rights_waiver_on_file` set to true; otherwise it is `EXPIRED` when that artist's `is_living` is false; and otherwise it is `ACTIVE`. A work's `condition_index`, `treatment_priority_score` and `treatment_priority_rank` all begin null, its `priority_basis` begins `NONE`, its `open_notice_count` and `maintenance_applications_ytd` begin at zero, and its `last_maintenance_completed_on` and `next_maintenance_due_on` begin null.

### 3.2. Condition Surveys, Photographic Documentation and the Condition Index

A `ConditionSurveyor` opens a survey in `DRAFT` against one work in one `cycle_year`, which must fall between 2000 and 2100. The payload names the `artwork_id`, the `assessed_on` date on which the survey was actually performed, and five defect subscores, each an integer from 0 for pristine to 4 for failed: `surface_score`, `structural_score`, `coating_score`, `mount_score` and `graffiti_score`. A freshly opened survey has `status` of `DRAFT`, `photo_count` at zero, an empty `photo_view_codes`, a null `condition_index`, a `recommendation` of `NONE`, `revision_rounds` at zero and both `submitted_by_user_id` and `finalized_by_user_id` null.

Photographic documentation is attached one record at a time, and only while the survey sits in `DRAFT` or `REVISION_REQUESTED`; an attempt from any other status draws `ERR_ASSESSMENT_INVALID_STATE`. Each attachment names a `view_code` identifying the vantage, a `media_ref` pointing at the stored image, and an optional `caption`. Each attachment increases `photo_count` by one and appends its `view_code` to `photo_view_codes`, which holds the distinct view codes in attachment order. The attachment is not itself a separately addressable record — `media_ref` and `caption` are validated and then discarded — so `photo_count` and `photo_view_codes` are the whole of a survey's photographic trace, and the response to an attachment is the updated survey.

Submission moves the survey to `SUBMITTED`, from `DRAFT` on the first pass and from `REVISION_REQUESTED` on any later pass, and may carry an optional `surveyor_note`. Submission requires at least three photographic records; a survey with `photo_count` below three is refused with `ERR_PHOTO_DOCUMENTATION_INSUFFICIENT`. On the first pass, submission additionally requires that the surveyed work has not left the collection. Every submission stamps `submitted_by_user_id` with the acting `X-User-ID`, restamping it on each round so that the identity recorded is always that of the most recent submitter.

Review belongs to the `ChiefConservator`, who may send a `SUBMITTED` survey back with a mandatory `reviewer_note`, moving it `SUBMITTED → REVISION_REQUESTED` and increasing `revision_rounds` by one. Two rounds are the ceiling: the request is permitted only while `revision_rounds` is below 2, so a third attempt to send the same survey back is refused with `ERR_REVISION_LIMIT_REACHED`. The loop `SUBMITTED → REVISION_REQUESTED → SUBMITTED` is the negotiation channel between surveyor and conservator, and it closes when the conservator finalizes instead of returning the work.

Finalization is the `ChiefConservator`'s act, carries an optional `finalization_note`, and moves the survey `SUBMITTED → FINALIZED`. It is barred to the user who submitted it: when the acting `X-User-ID` equals `submitted_by_user_id`, the request is refused with `ERR_SEGREGATION_OF_DUTIES`. It is also barred when the surveyed work has already left the collection. On success `finalized_by_user_id` records the acting user.

Finalization computes the survey's `condition_index`. Each of the five subscores is multiplied by a weight chosen by the work's `material_class`, and the five products are summed into a weighted defect figure that ranges from 0.0 for a pristine work to 4.0 for a work failed on every axis. The weight sets are:

- `BRONZE`: surface 0.30, structural 0.25, coating 0.20, mount 0.15, graffiti 0.10.
- `PAINTED_STEEL`: surface 0.20, structural 0.20, coating 0.35, mount 0.15, graffiti 0.10.
- `STONE`: surface 0.25, structural 0.35, coating 0.05, mount 0.20, graffiti 0.15.
- `MURAL_COATING`: surface 0.35, structural 0.10, coating 0.30, mount 0.05, graffiti 0.20.

An environmental penalty is then computed separately, from the `exposure_class` of the site the work currently occupies: 6.0 for `COASTAL`, 3.0 for `URBAN`, 1.5 for `PARK` and 0.0 for `INTERIOR`. That figure is multiplied by a severity factor which is 1.0 when the largest of the five subscores is exactly 4, and 0.5 otherwise — so the exposure penalty doubles the moment any single axis has failed outright. The index is then 100, less 25 times the weighted defect figure, less the penalty, rounded half up to one decimal place and finally floored at 0.0. The penalty is subtracted after the weighted defect term and is never folded into it.

The index sorts the survey into a `recommendation` band: `NONE` when the index is 75.0 or above, `ROUTINE` when it is at least 55.0 but below 75.0, `PRIORITY` when it is at least 30.0 but below 55.0, and `URGENT` when it is below 30.0. The value 55.0 is the collection's treatment trigger, and it recurs throughout this specification.

Finalization then runs Cascade A. Hop 1: every other survey on the same work that was sitting in `FINALIZED` moves `FINALIZED → SUPERSEDED`, so a work has at most one finalized survey at a time. Hop 2: because this survey is now finalized, the work's `condition_index` is set to the survey's index, its `treatment_priority_score` is recomputed under the single-assessment variant described in §3.9, its `priority_basis` is set to `SINGLE_ASSESSMENT`, and its conservation dimension moves `MONITORED → TREATMENT_REQUIRED` or `STABILIZED → TREATMENT_REQUIRED` when the new index is below 55.0. That a stabilized work can be flagged again is intentional: the conservation dimension is a cycle, not a ladder. Hop 3: because the work now requires treatment, every maintenance visit on that work still sitting in `SCHEDULED` whose protocol does not require a conservator moves `SCHEDULED → ABORTED` with `abort_reason` set to `SUPERSEDED_BY_TREATMENT`; visits whose protocol does require a conservator are left alone. Hop 3 fires only where hop 2 actually moved the conservation dimension into `TREATMENT_REQUIRED` — where the new index is 55.0 or above, or where the work already stood in `TREATMENT_REQUIRED` or `TREATMENT_IN_PROGRESS`, no visit is aborted and hops 4 and 5 have nothing to do. Hop 4: because those visits are now aborted, every funding allocation attached to them in `RESERVED` or `COMMITTED` moves to `RELEASED` with `release_reason` set to `VISIT_ABORTED`. Hop 5: because those allocations are released, each affected pool's `available_cents` is recomputed and rises by the released `amount_cents`. Finally, the treatment priority ranking is recomputed across the whole cohort of works whose `conservation_status` is `TREATMENT_REQUIRED` or `TREATMENT_IN_PROGRESS`.

### 3.3. Routine Material Care: Protocols, Windows and the Graffiti Response Clock

Routine care is described by protocols, declared by a `ChiefConservator` or a `PublicArtManager`. A protocol carries a `protocol_code` unique across protocols, the `material_class` it applies to, and a `method` drawn from `WASH`, `WAX`, `GRAFFITI_REMOVAL`, `COATING_RENEWAL` and `INSPECTION`. Its `cycle_days`, between 1 and 3650, is the interval between applications and sets a work's next due date on completion. Its `max_annual_applications` defaults to 4 and must be at least 1, capping how many times the protocol may be completed on one work in a single clock year. The boolean `requires_conservator`, defaulting to false, marks methods that may only be performed under a conservator engagement — and, as Cascade A hop 3 shows, it is what shields a scheduled visit from being aborted by a new treatment requirement. A `solvent_class` of `NONE`, `MILD` or `AGGRESSIVE`, defaulting to `NONE`, records how aggressive the cleaning agent is.

Scheduling a visit is open to `MaintenanceCrew` and `ChiefConservator`. The payload names the `artwork_id`, the `protocol_id`, and a work window bounded by `window_start` and `window_end`, with the end strictly after the start. An optional `crew_note` carries free-text instruction to the crew. The protocol's `material_class` must equal the work's `material_class`, and a mismatch is refused with `ERR_PROTOCOL_MATERIAL_MISMATCH`. A window may not be scheduled into the past: `window_start` must be at or after the logical clock, and an earlier value draws `ERR_WINDOW_IN_PAST`.

Site work capacity is enforced at scheduling time. Site work windows are treated as **closed** intervals running from `window_start` through `window_end` inclusive, which means two windows collide even when one begins at the exact instant the other ends. The count of visits at the same site whose `status` is `SCHEDULED` or `IN_PROGRESS` and whose window collides with the requested one must be strictly less than that site's `concurrent_work_capacity`; otherwise the request is refused with `ERR_SITE_WORK_CAPACITY_CONFLICT`. A candidate visit's site for this purpose is the current `site_id` of the artwork it names, read at the moment of the check rather than remembered from scheduling time, and visits on the very work being scheduled count like any other.

Graffiti response has its own clock. When a visit is scheduled to clear a tag, the payload carries `graffiti_reported_at`, the instant the graffiti was reported, and the server derives `sla_deadline_at` by adding a response allowance chosen by the work's material: `MURAL_COATING` must be cleared within 48 hours, `PAINTED_STEEL` within three days, and both `BRONZE` and `STONE` within five days. The derivation keys on the presence of `graffiti_reported_at` alone: the protocol's `method` is never consulted, so any visit carrying that instant acquires a deadline, and the instant itself is accepted whether it falls before or after the logical clock. When `graffiti_reported_at` is omitted it stays null, `sla_deadline_at` stays null, and `sla_breached` stays false for the life of the visit.

A `MaintenanceCrew` member starts a visit, moving it `SCHEDULED → IN_PROGRESS` with an optional `crew_note` that, when supplied, replaces the `crew_note` recorded at scheduling and is otherwise left as it stands. The logical clock must be at or after `window_start` — an earlier attempt draws `ERR_VISIT_WINDOW_NOT_OPEN` — and the work's `custody_status` must be `ON_VIEW` or `IN_STORAGE`, since a work already `IN_TREATMENT` cannot receive routine care; that failure is `ERR_ARTWORK_CUSTODY_INVALID`. Starting stamps `started_at` from the logical clock and moves any funding allocation attached to the visit from `RESERVED` to `COMMITTED`.

Completing a visit, again a crew act with an optional `completion_note`, moves it `IN_PROGRESS → COMPLETED`. Completion is refused with `ERR_MAX_ANNUAL_APPLICATIONS` unless the number of already-`COMPLETED` visits for this same work and this same protocol within the logical clock's year is strictly less than the protocol's `max_annual_applications`. On success `completed_at` is stamped from the logical clock and the SLA is judged: where a deadline exists, `sla_breached` becomes true only when `completed_at` falls strictly after `sla_deadline_at`, so a crew that finishes at the deadline instant exactly is compliant. The work's `last_maintenance_completed_on` becomes the calendar date of `completed_at`, its `next_maintenance_due_on` becomes that same date advanced by the completed protocol's `cycle_days`, and its `maintenance_applications_ytd` is recomputed as the number of its completed visits whose completion year matches the logical clock's year. Any funding allocation attached to the visit moves from `COMMITTED` to `DISBURSED`.

A scheduled visit can also die without ever starting. Cascade A hop 3 aborts it with `abort_reason` of `SUPERSEDED_BY_TREATMENT` when a survey flags the work for treatment; Cascade B hop 2 aborts it with `abort_reason` of `ARTWORK_DEACCESSIONED` when the work leaves the collection. In both cases the abort is followed immediately by the release of any `RESERVED` or `COMMITTED` allocation attached to the visit, carrying `release_reason` of `VISIT_ABORTED`. A visit that has never been aborted keeps `abort_reason` at `NONE`.

### 3.4. Engaging a Conservator: Vendors, Proposals and the Estimate

Conservation vendors are registered by the `PublicArtManager` alone. A vendor record names the `firm_name`, an `accreditation` of `AIC_PA`, `AIC_ASSOCIATE` or `NONE`, a non-empty `material_specialties` array drawn from `BRONZE`, `PAINTED_STEEL`, `STONE` and `MURAL_COATING`, an `hourly_rate_cents` of at least 1 cent that is the contracted labour rate, and an `insurance_expires_on` date on which liability cover lapses. A new vendor is created with `status` of `ACTIVE` and `active_engagement_count` at zero, that count being maintained as the number of the vendor's proposals sitting in `APPROVED` or `IN_EXECUTION`. The manager may later suspend a vendor with a mandatory `reason`, moving `status` from `ACTIVE` to `SUSPENDED`, after which no new proposal may be approved for them. Suspension is idempotent rather than state-guarded: suspending a vendor already in `SUSPENDED` succeeds, returns the vendor and leaves its `updated_at` and `version` alone.

Drafting a proposal is the `ChiefConservator`'s act. The payload names the `artwork_id`, the `conservator_id` of the engaged firm, the `assessment_id` of the finalized survey justifying the work, a `treatment_scope` drawn from `STABILIZATION`, `SURFACE`, `COATING`, `STRUCTURAL` and `GRAFFITI`, an engagement window bounded by `engagement_start` and `engagement_end` with the end strictly after the start, and `expected_artwork_version`. The optional `alters_appearance` boolean, defaulting to false, declares whether the treatment changes how the work looks, and it is what pulls the artist consultation and notice machinery into the approval path. The cited survey must be in `FINALIZED` and must belong to the same work as the proposal, failing which the draft is refused with `ERR_ASSESSMENT_NOT_FINALIZED`. Only one live proposal may exist per survey: if another proposal already cites the same `assessment_id` and sits in `DRAFT`, `SUBMITTED`, `REVISION_REQUESTED`, `APPROVED` or `IN_EXECUTION`, the draft is refused with `ERR_DUPLICATE_ACTIVE_PROPOSAL`. A successful draft is created in `DRAFT` with an empty `line_items`, `subtotal_cents`, `overhead_cents`, `contingency_cents`, `mobilization_cents` and `estimate_total_cents` all at zero, `revision_rounds` at zero, `submitted_by_user_id` and `approved_by_user_id` null, `withdraw_reason` of `NONE` and `pinned_estimate_total_cents` null; `expected_artwork_version` is consumed by the check and not stored on the proposal. It also increments the referenced artwork's own `version`, which is precisely why a subsequent draft against the same work needs a re-read.

Cost lines are appended to a proposal one at a time, again by the `ChiefConservator`, and the collection is append-only — no line is ever removed or excluded. A line may be appended only while the proposal sits in `DRAFT` or `REVISION_REQUESTED`; an attempt from any other status draws `ERR_PROPOSAL_INVALID_STATE`. Each line carries `labor_hours`, a number at or above 0 which need not be whole, a `complexity_class` drawn from the same five members as `treatment_scope`, a `materials_cents` integer at or above 0, and an optional `description` that is validated and then discarded rather than kept on the stored line. The line's own labour cost is `labor_hours` multiplied by the engaged conservator's `hourly_rate_cents` as it stands at the moment the line is added, multiplied again by a complexity factor of 1.00 for `STABILIZATION`, 1.15 for `SURFACE`, 1.25 for `COATING`, 1.40 for `STRUCTURAL` and 1.10 for `GRAFFITI`, with that product rounded half up to a whole cent and stored on the line as `labor_cents`. The line's `line_total_cents` is its `labor_cents` plus its `materials_cents`. A stored line therefore holds exactly five fields — `labor_hours`, `complexity_class`, `materials_cents`, `labor_cents` and `line_total_cents` — and appending one returns the whole updated proposal.

Appending a line recomputes the whole estimate in a pinned order. `subtotal_cents` is the sum of the per-line `line_total_cents` values, each already rounded — rounding per line and then summing is normative, and it differs by a cent from summing raw products and rounding once whenever a line's labour lands on a half cent. `overhead_cents` is 11.5 percent of `subtotal_cents`, rounded half up to a whole cent. `contingency_cents` is 7.5 percent of the sum of `subtotal_cents` and `overhead_cents`, rounded half up to a whole cent — contingency is computed after overhead and therefore includes it, and computing contingency from the bare subtotal is wrong. `mobilization_cents` is a flat 45,000 cents (450 dollars) whenever at least one line exists and zero when the collection is empty. `estimate_total_cents` is the sum of `subtotal_cents`, `overhead_cents`, `contingency_cents` and `mobilization_cents`.

Submission by the `ChiefConservator`, with an optional `submitter_note`, moves the proposal `DRAFT → SUBMITTED` on the first pass and `REVISION_REQUESTED → SUBMITTED` on later passes, and requires a non-empty `line_items` in both cases, an empty collection drawing `ERR_PROPOSAL_INVALID_STATE`; that check rides with the state precondition at step 9 of §2.8 and therefore fires ahead of the deaccession guard. The first pass additionally requires that the target work has not left the collection. Each submission stamps `submitted_by_user_id` with the acting `X-User-ID`. The `PublicArtManager` may send a `SUBMITTED` proposal back with a mandatory `reviewer_note`, moving it `SUBMITTED → REVISION_REQUESTED` and increasing `revision_rounds` by one, permitted only while `revision_rounds` is below 2 — the third such request on the same proposal is refused with `ERR_REVISION_LIMIT_REACHED`. The loop `SUBMITTED → REVISION_REQUESTED → SUBMITTED` is the cost negotiation, and every re-submission recomputes nothing on its own; the estimate only moves when lines are added.

The manager may instead reject a `SUBMITTED` proposal with a mandatory `rejection_reason`, moving it `SUBMITTED → REJECTED`. Rejection releases every funding allocation attached to the proposal that sits in `RESERVED` or `COMMITTED`, stamping `release_reason` as `PROPOSAL_REJECTED`, and the affected pool's `available_cents` rises accordingly.

### 3.5. Approval Gates and Treatment Execution

Approval is the `PublicArtManager`'s decision and carries an optional `approval_note`. It moves the proposal `SUBMITTED → APPROVED` and is the most heavily guarded operation in the system, because it commits an outside vendor, a schedule, a legal consent and public money in one act. Five conditions must hold, and per §2.8 they are evaluated in a fixed order so that a consent failure is never masked by a money failure.

First, artist consent, in three graduated checks. When the proposal has `alters_appearance` set to true and the target work's `moral_rights_status` is `ACTIVE`, an artist consultation naming this proposal must exist at all — none, and the approval is refused with `ERR_ARTIST_CONSULTATION_REQUIRED`. If one exists but is still `PENDING`, the approval is refused with `ERR_ARTIST_CONSULTATION_PENDING`. If it exists and is `OBJECTED`, the approval is refused with `ERR_ARTIST_OBJECTION_UNRESOLVED`. Only `CONCURRED` or `LAPSED` clears the gate. Where more than one consultation names the proposal the whole set is read together: an `OBJECTED` row anywhere in the set refuses the approval even if another row has concurred or lapsed, and `ERR_ARTIST_CONSULTATION_PENDING` is raised only where the set holds a `PENDING` row and no `CONCURRED` or `LAPSED` row. A consultation counts for this gate purely by naming the proposal in its `proposal_id`; its `artwork_id`, `artist_id` and `subject` are not required to agree with anything. Where `alters_appearance` is false, or the work's `moral_rights_status` is `WAIVED` or `EXPIRED`, none of these three checks applies.

Second, vendor eligibility. The engaged conservator's `status` must be `ACTIVE`, their `insurance_expires_on` must fall on or after the date of `engagement_end`, and the work's `material_class` must be a member of the conservator's `material_specialties`. Any of those three failing yields `ERR_CONSERVATOR_NOT_ELIGIBLE`.

Third, engagement exclusivity. A conservator's engagement windows are treated as **half-open** intervals — they include `engagement_start` and exclude `engagement_end` — and each is padded by a 48-hour mobilisation buffer on both sides. A collision therefore exists with another proposal of the same conservator sitting in `APPROVED` or `IN_EXECUTION` exactly when this proposal's `engagement_start` falls before that proposal's `engagement_end` advanced by 48 hours, and that proposal's `engagement_start` falls before this proposal's `engagement_end` advanced by 48 hours. Any such collision yields `ERR_CONSERVATOR_WINDOW_CONFLICT`. Note the deliberate contrast with §3.3: site work windows are closed intervals where touching endpoints collide, while conservator engagement windows are half-open and buffered.

Fourth, funding. A funding allocation naming this proposal must exist in `RESERVED` status with an `amount_cents` greater than or equal to the proposal's current `estimate_total_cents`; otherwise the approval is refused with `ERR_FUNDING_NOT_RESERVED`.

On success, `pinned_estimate_total_cents` freezes at the proposal's `estimate_total_cents` at that instant, which later becomes the basis of a restoration insurance claim, and `approved_by_user_id` records the acting user. The engaged conservator's `active_engagement_count` rises by one. Cascade C then runs: every other proposal on the same work sitting in `DRAFT`, `SUBMITTED` or `REVISION_REQUESTED` moves to `WITHDRAWN` with `withdraw_reason` set to `PROPOSAL_SUPERSEDED`; every `RESERVED` or `COMMITTED` allocation attached to those superseded proposals moves to `RELEASED` with `release_reason` set to `PROPOSAL_WITHDRAWN`; and each affected pool's `available_cents` is recomputed upward by the released amounts.

Execution belongs to the engaged vendor and to no one else — the acting `X-User-ID` must equal the proposal's `conservator_id`, and a mismatch draws `ERR_NOT_RESOURCE_OWNER`. Starting execution, with an optional `mobilization_note`, moves the proposal `APPROVED → IN_EXECUTION`. It requires the work's `custody_status` to be `ON_VIEW` or `IN_STORAGE`, failing which the request draws `ERR_ARTWORK_CUSTODY_INVALID`, and it requires that no maintenance visit on the same work is currently `IN_PROGRESS`, a collision reported under that same code `ERR_ARTWORK_CUSTODY_INVALID`. On success the work's custody moves `ON_VIEW → IN_TREATMENT` or `IN_STORAGE → IN_TREATMENT`, and its conservation dimension moves `TREATMENT_REQUIRED → TREATMENT_IN_PROGRESS` only where it currently stands at `TREATMENT_REQUIRED`; any other conservation value is left exactly as it is. Where the work was `ON_VIEW` the site's `installed_units_used` is deliberately left unchanged, because a work under treatment still occupies its site; where the work was `IN_STORAGE` that same footprint rule cuts the other way and the site's `installed_units_used` rises by the work's `footprint_units`, since under §3.1 an `IN_TREATMENT` work consumes footprint and a stored one does not. The proposal's `RESERVED` allocation moves to `COMMITTED`.

Completion, also the vendor's act, carries a mandatory `completion_report_ref` and moves the proposal `IN_EXECUTION → COMPLETED`. The work's custody returns `IN_TREATMENT → ON_VIEW` and its conservation dimension moves `TREATMENT_IN_PROGRESS → STABILIZED`. Its `treatment_priority_score` and `treatment_priority_rank` are cleared to null and its `priority_basis` returns to `NONE`, after which the ranks of the remaining cohort are recomputed; its `condition_index` is deliberately not cleared and stands as the last finalized survey left it. The proposal's `COMMITTED` allocation moves to `DISBURSED`, the conservator's `active_engagement_count` falls by one, and every damage incident whose `linked_proposal_id` names this proposal and whose `damage_status` is `TRIAGED` moves `TRIAGED → RESOLVED`.

Proposals also die by cascade. When a deaccession execution makes the work's custody terminal, Cascade B hop 2 moves every proposal on that work sitting in `DRAFT`, `SUBMITTED`, `REVISION_REQUESTED` or `APPROVED` to `WITHDRAWN` with `withdraw_reason` set to `ARTWORK_DEACCESSIONED`. All four branches behave alike in one respect: every `RESERVED` or `COMMITTED` allocation attached to any of them is released with `release_reason` of `PROPOSAL_WITHDRAWN` in hop 3, and each affected pool's `available_cents` rises in hop 4. They differ in exactly one respect: the `APPROVED → WITHDRAWN` branch also decreases the engaged conservator's `active_engagement_count` by one, because that engagement had already been counted, whereas the `DRAFT → WITHDRAWN`, `SUBMITTED → WITHDRAWN` and `REVISION_REQUESTED → WITHDRAWN` branches leave the count untouched. `COMPLETED`, `REJECTED` and `WITHDRAWN` are terminal for a proposal.

### 3.6. Moral Rights: Consultations and Statutory Notices

Two distinct instruments serve the artist's interest, and confusing them is a common error. A **consultation** asks the artist's view and yields a recorded opinion. A **notice** starts a statutory waiting period and yields an authorisation to act. Alteration requires the former; relocation, removal and destruction require the latter. In neither instrument is the named `artist_id` required to be the work's attributed artist, and a consultation's optional `proposal_id` need not name a proposal on the same work; the identifiers must resolve, but no such agreement is checked.

A consultation is opened by a `ChiefConservator` or a `PublicArtManager`, naming the `artwork_id`, the `artist_id` and a `subject` drawn from `TREATMENT`, `RELOCATION`, `REMOVAL` and `DEACCESSION`. An optional `proposal_id` links the consultation to a specific treatment proposal and is what the approval gate in §3.5 looks for; left unset it stays null. Creation stamps `sent_on` with the logical clock's calendar date and derives `due_at` by advancing the logical clock by the artist's `consultation_response_days`. The row is created in `PENDING` with `response_note` and `responded_at` null — except where the work's `moral_rights_status` is `WAIVED` at creation time, in which case the row is stamped `WAIVED` immediately and `responded_at` stays null. A consultation on a waived artist's work is therefore never observable in `PENDING`.

The artist answers through their representative, and only for their own work: the acting `X-User-ID` must equal the consultation's `artist_id`. The response payload carries a `response` of either `CONCUR` or `OBJECT` and an optional `response_note` holding the artist's written reply. A `CONCUR` moves the row `PENDING → CONCURRED` and an `OBJECT` moves it `PENDING → OBJECTED`; both stamp `responded_at` from the logical clock, and both require the logical clock to be strictly before `due_at`. A response arriving at or after `due_at` is refused with `ERR_CONSULTATION_WINDOW_CLOSED`. An objection does not merely record displeasure — while the row stands in `OBJECTED`, the linked proposal cannot be approved.

Silence is also an answer. The cycle checkpoint moves every `PENDING` consultation whose `due_at` is at or before the logical clock to `LAPSED`, and a lapsed consultation clears the approval gate exactly as a concurrence does. Cascade B hop 2 also moves `PENDING` consultations to `LAPSED` when the work leaves the collection. `CONCURRED`, `OBJECTED`, `LAPSED` and `WAIVED` are all terminal.

A notice is sent by a `PublicArtManager` or a `CollectionsRegistrar`, naming the `artwork_id`, the `artist_id`, and an `action_type` drawn from `ALTERATION`, `RELOCATION`, `REMOVAL` and `DESTRUCTION`. Creation stamps `sent_at` from the logical clock, derives `earliest_action_at` by advancing that instant by the artist's `notice_wait_days`, sets `status` to `SENT`, leaves `acknowledged_at` and `consumed_by_ref` null, and raises the work's `open_notice_count` by one — that counter being maintained as the number of the work's notices sitting in `SENT`, `ACKNOWLEDGED` or `WAIT_ELAPSED`.

A notice matures by one of two routes. The artist's representative may acknowledge it, moving `SENT → ACKNOWLEDGED` with an optional `acknowledgement_note` and stamping `acknowledged_at`; this is permitted only from `SENT`, only by the artist named on the notice, and an attempt from any other status draws `ERR_NOTICE_INVALID_STATE`. Alternatively the cycle checkpoint moves a `SENT` notice whose `earliest_action_at` is at or before the logical clock to `WAIT_ELAPSED`. Both `ACKNOWLEDGED` and `WAIT_ELAPSED` are usable authorisations.

Relocating or deaccessioning a work whose `moral_rights_status` is `ACTIVE` requires such an authorisation. A notice on that work whose `action_type` matches the action being taken and whose `status` is `ACKNOWLEDGED` or `WAIT_ELAPSED` must exist, and absent one the action is refused with `ERR_MORAL_RIGHTS_NOTICE_REQUIRED`. The matching notice's `earliest_action_at` must be at or before the logical clock; where several matching notices exist the earliest-created matured one is the authorising notice, `ERR_MORAL_RIGHTS_WAIT_ACTIVE` is raised only when no candidate has matured, and the action is permitted at the `earliest_action_at` instant exactly. When the action proceeds, the authorising notice is spent — moving `ACKNOWLEDGED → CONSUMED` where the artist had acknowledged it, or `WAIT_ELAPSED → CONSUMED` where the waiting period had simply run out — its `consumed_by_ref` records the identifier of the act that used it, which is the deaccession case's `id` for a deaccession and, because a relocation is not itself a persisted record, the relocated `Artwork`'s own `id` for a withdrawal into storage, and the work's `open_notice_count` falls by one. `CONSUMED` and `VOID` are terminal.

Notices are also voided in bulk. When Cascade B hop 2 runs, every notice on the departing work in `SENT`, `ACKNOWLEDGED` or `WAIT_ELAPSED` other than the one the execution consumed moves to `VOID`, each decrement lowering the work's `open_notice_count` by one.

### 3.7. Custody Moves and Relocation

Physical relocation is the `CollectionsRegistrar`'s exclusive act and covers two opposite moves distinguished by the payload. Setting `to_storage` to true withdraws a work from public view, moving custody `ON_VIEW → IN_STORAGE`; supplying a `to_site_id` reinstalls a stored work, moving custody `IN_STORAGE → ON_VIEW`. Exactly one of the two must be given: supplying both, or neither — a `to_storage` that is false or absent with no `to_site_id` — is a shape failure drawing `ERR_INVALID_REQUEST`, decided before any identifier in the body is resolved. An optional `relocation_note` records the reason and is not retained on the work. Either direction is refused with `ERR_ARTWORK_CUSTODY_INVALID` when the work's custody is not the expected origin — a work `IN_TREATMENT` cannot be relocated at all — and with `ERR_ARTWORK_DEACCESSIONED` when the work has already left the collection.

Withdrawal into storage counts as a removal from public view for moral-rights purposes: where the work's `moral_rights_status` is `ACTIVE`, a matured `RELOCATION` notice must exist and is consumed by the move, as described in §3.6. The vacated site's `installed_units_used` falls by the work's `footprint_units`, while the work keeps its `site_id` unchanged — a stored work still names the site it left, which is what a later reinstallation overwrites.

Reinstallation is the compensating move, and the site-footprint invariant must hold again afterwards. The target site's existing `installed_units_used` plus the work's `footprint_units` must not exceed that site's `capacity_units`, failing which the move is refused with `ERR_SITE_CAPACITY_EXCEEDED`. On success the work's `site_id` becomes the named target and that site's `installed_units_used` rises by the work's `footprint_units`.

### 3.8. Deaccession: Criteria, Public Comment, Ballots and Disposition

Removing a work from the collection permanently is a public act, and the process is built to be slow. A `PublicArtManager` opens a case naming the `artwork_id`, a non-empty `criteria` array drawn from `DETERIORATION_BEYOND_REPAIR`, `PUBLIC_SAFETY_HAZARD`, `SITE_REDEVELOPMENT`, `DUPLICATE_HOLDING` and `LACK_OF_RELEVANCE`, and an intended `disposition` of `SALE`, `TRANSFER`, `DESTRUCTION` or `RETURN_TO_ARTIST`. A `disposition_target_ref` naming the receiving institution or buyer may be supplied now or later, and `comment_days` sets the length of the public comment period, defaulting to 45 days and accepted anywhere from 7 to 180. The case is created in `INITIATED` with `initiated_by_user_id` stamped from the acting `X-User-ID`, an empty `vote_records`, all four ballot counters at zero, and `decision_ratio`, `public_comment_opens_on`, `public_comment_closes_at` and `executed_at` all null.

The manager advances the case with an optional `advance_note`. The first advance moves it `INITIATED → PUBLIC_COMMENT`, requires that the work has not already left the collection, sets `public_comment_opens_on` to the logical clock's calendar date and derives `public_comment_closes_at` by advancing the logical clock by `comment_days` days. The second advance moves it `PUBLIC_COMMENT → BOARD_REVIEW` and requires the logical clock to be at or after `public_comment_closes_at`; an earlier attempt is refused with `ERR_PUBLIC_COMMENT_OPEN`.

Balloting is open to `ArtCommissionMember` and `PublicArtManager` and happens while the case sits in `BOARD_REVIEW`. Each ballot carries a `ballot` value of `APPROVE`, `DENY`, `ABSTAIN` or `RECUSE` and an optional `ballot_note`, and is appended to `vote_records` as an entry holding `member_user_id` taken from the acting `X-User-ID`, the `ballot` cast, and a `created_at` stamp. The matching counter — `approve_count`, `deny_count`, `abstain_count` or `recuse_count` — rises by one. A member may vote once: a second ballot bearing a `member_user_id` already present in `vote_records` is refused with `ERR_DUPLICATE_BALLOT`. The initiator is not disenfranchised but is disarmed — where the acting `X-User-ID` equals `initiated_by_user_id`, an `APPROVE` or `DENY` ballot is refused with `ERR_INITIATOR_CANNOT_VOTE`, while `ABSTAIN` and `RECUSE` remain available to them.

Each ballot triggers an automatic tally. Quorum is reached when the count of ballots that are not recusals — that is, `approve_count` plus `deny_count` plus `abstain_count` — is at least 5; recusals are excluded from quorum entirely. At quorum, `decision_ratio` is the `approve_count` divided by the sum of `approve_count` and `deny_count`, and is defined as exactly 0 in the degenerate case where that denominator is zero because every quorum ballot was an abstention. A ratio of 0.60 or above moves the case `BOARD_REVIEW → APPROVED`; a ratio below 0.60 — including that all-abstention case — moves it `BOARD_REVIEW → DENIED`. Either way the `decision_ratio` is pinned at the value that produced the decision, and it is pinned unrounded, so a two-approve, one-deny quorum records a repeating fraction rather than a tidy two-place figure. Because the tally moves the case out of `BOARD_REVIEW`, any further ballot on it is refused with `ERR_CASE_INVALID_STATE`. `DENIED` is terminal.

Execution is the manager's final act, carries an optional `execution_note` and moves the case `APPROVED → EXECUTED`, stamping `executed_at` from the logical clock. Four preconditions apply. A `DESTRUCTION` disposition may only execute when the work's `recognized_stature` is false; a protected work draws `ERR_RECOGNIZED_STATURE_PROTECTED`. Where the work's `moral_rights_status` is `ACTIVE`, a matured notice on that work whose `action_type` is `REMOVAL` or `DESTRUCTION` must exist in `ACKNOWLEDGED` or `WAIT_ELAPSED` with an `earliest_action_at` at or before the logical clock, subject to the two failures in §3.6. A `SALE` or `TRANSFER` disposition requires a non-null `disposition_target_ref`, failing which the request draws `ERR_DISPOSITION_TARGET_REQUIRED`.

Execution then runs Cascade B in full. Hop 1: the work's `custody_status` becomes `DESTROYED` when the disposition is `DESTRUCTION` and `DEACCESSIONED` for `SALE`, `TRANSFER` or `RETURN_TO_ARTIST`, moving from `ON_VIEW` or from `IN_STORAGE` in either case; where the work was `ON_VIEW`, its site's `installed_units_used` falls by the work's `footprint_units`, and where it was already `IN_STORAGE` no site adjustment is needed because none was being consumed. Hop 2: the work's non-terminal treatment proposals are withdrawn, its `SCHEDULED` maintenance visits are aborted, its `PENDING` artist consultations lapse, and its open moral-rights notices other than the consumed one are voided, all as detailed in §3.3, §3.5 and §3.6. Hop 3: the funding allocations held by those withdrawn proposals and aborted visits, in `RESERVED` or `COMMITTED`, are released. Hop 4: each affected pool's `available_cents` rises by the released `amount_cents`. Finally the authorising notice moves to `CONSUMED` with its `consumed_by_ref` set to this case's identifier.

### 3.9. Priority Ranking and the Cycle Checkpoint

A treatment priority score answers one question: of the works needing attention, which should be treated first. It is a product of four factors. The **deficit** is 100 less the source survey's `condition_index`. The **significance factor** is 1.5 for a `LANDMARK` work, 1.2 for a `SIGNIFICANT` one and 1.0 for a `STANDARD` one. The **exposure factor**, read from the `exposure_class` of the site the work occupies, is 1.3 for `COASTAL`, 1.25 for `URBAN`, 1.1 for `PARK` and 1.0 for `INTERIOR`. The **deferral factor** starts at 1 and grows by 0.004 for each whole day between the source survey's `assessed_on` date and the logical clock's date, a count that is never negative, and is capped at 1.60 — a ceiling reached after 150 days of deferral, beyond which further delay no longer improves a work's standing in the queue. The score is the product of all four factors, rounded half up to two decimal places, with that rounding applied once to the final product and never to an intermediate factor.

Two variants supply the source survey, and they are not interchangeable. Under the **single-assessment** variant, which runs as Cascade A hop 2 when a survey is finalized, the source is that very survey and the deferral day count is pinned to zero, so the deferral factor is exactly 1.0 and the score is the undeferred product; the work's `priority_basis` is set to `SINGLE_ASSESSMENT`. Under the **cycle-cohort** variant, which runs at the cycle checkpoint, the source is the *earliest* finalized survey of the named cycle year for that work — ordered by `assessed_on` ascending and, where two surveys share a date, by `created_at` ascending — and the deferral day count is measured from that survey's `assessed_on` to the logical clock; the work's `priority_basis` is set to `CYCLE_COHORT`. Because the cohort variant reaches back to the oldest survey of the cycle rather than the newest, the same work scores strictly higher under it than under the single-assessment variant whenever that survey predates the clock.

Ranking is a whole-collection operation. The cohort is every work whose `conservation_status` is `TREATMENT_REQUIRED` or `TREATMENT_IN_PROGRESS`, custody being no part of the test — the conservation dimension is untouched by a deaccession, so a work that has left the collection still reading `TREATMENT_REQUIRED` remains in the cohort and keeps a rank; the cohort is ordered by `treatment_priority_score` descending and, where two works tie, by `created_at` ascending with insertion sequence settling any further tie, and `treatment_priority_rank` is the 1-based position in that order. Works outside the cohort carry a null rank.

The cycle checkpoint is the `PublicArtManager`'s scheduled sweep and takes a single `cycle_year`. It performs four passes. It rescores every work holding at least one finalized survey in that cycle year under the cycle-cohort variant — whatever the work's conservation status or custody, so a `MONITORED` work acquires a score and a `CYCLE_COHORT` basis while its rank stays null for want of cohort membership — sets each such work's `priority_basis` to `CYCLE_COHORT` and recomputes cohort ranks. This pass is the single exception to §2.5's no-op qualification: it refreshes each rescored work's `updated_at` and increments its `version` whether or not the recomputed score differs from the one already held, and `artworks_rescored` counts every work it rescored on that basis. It moves every `PENDING` artist consultation whose `due_at` is at or before the logical clock to `LAPSED`. It moves every `SENT` moral-rights notice whose `earliest_action_at` is at or before the logical clock to `WAIT_ELAPSED`. And it closes the conservation cycle: a work whose `conservation_status` is `STABILIZED` returns `STABILIZED → MONITORED` when it holds a finalized survey in the named cycle year whose `condition_index` is 55.0 or above — a work that has been treated and then re-surveyed as healthy goes back into ordinary monitoring, completing the loop `MONITORED → TREATMENT_REQUIRED → TREATMENT_IN_PROGRESS → STABILIZED → MONITORED`. The checkpoint reports what it did, echoing the `cycle_year` it ran for alongside `artworks_rescored`, `consultations_lapsed`, `notices_elapsed` and `artworks_returned_to_monitored`.

### 3.10. Funding: Endowment Draws, Set-Asides and Reservations

Conservation is paid for from two kinds of pool, both opened by the `FinanceOfficer`. A pool carries a `pool_code` unique across pools, a `pool_type` of `ENDOWMENT` or `PERCENT_FOR_ART`, and a `fiscal_year` between 2000 and 2100. An endowment is described by its `principal_cents`, a non-negative amount defaulting to zero, and its `draw_rate_bps`, an annual draw rate in basis points defaulting to zero and capped at 2000 — that is, at 20 percent. A percent-for-art pool is described instead by its `set_aside_cents`, a non-negative amount defaulting to zero. By convention an endowment carries no set-aside and a percent-for-art pool carries neither principal nor draw rate, but the convention is not enforced: all three amounts are accepted and stored on either type, and the draw computation simply ignores whichever ones its type does not use.

The authorised draw is computed at pool creation and depends on the type. For a `PERCENT_FOR_ART` pool the amount authorised before fees is simply the `set_aside_cents`, and `admin_fee_cents` is zero — set-asides carry no administrative charge. For an `ENDOWMENT` pool the gross draw is the `principal_cents` multiplied by the `draw_rate_bps` and divided by 10,000, rounded half up to a whole cent. That gross figure then selects a supplemental tier: no supplement at all when the gross draw is below 5,000,000 cents (50,000 dollars); a supplement of 75 basis points when the gross draw is at least 5,000,000 cents but below 20,000,000 cents (200,000 dollars); and a supplement of 125 basis points when the gross draw is 20,000,000 cents or more. Tier floors are inclusive, so a gross draw of exactly 20,000,000 cents selects the 125-basis-point tier. The supplemental amount is the `principal_cents` multiplied by the selected tier's basis points and divided by 10,000, rounded half up to a whole cent, and the amount authorised before fees is the gross draw plus that supplement. The administrative fee is then 2.25 percent of that pre-fee authorised amount, rounded half up to a whole cent, and recorded as `admin_fee_cents`.

Tier selection is pinned to the **gross, pre-fee** draw. This matters because the fee depends on the authorised amount while the authorised amount depends on a tier keyed to the draw, and selecting the tier from the post-fee figure would make the computation circular and the result ill-defined.

`draw_authorized_cents` is the pre-fee authorised amount less `admin_fee_cents`. A pool's `available_cents` is then its `draw_authorized_cents`, plus its `recovery_credits_cents` — the running total of insurance settlements credited back to it, which begins at zero — less the total `amount_cents` of the pool's allocations sitting in `RESERVED`, `COMMITTED` or `DISBURSED`. Allocations in `RELEASED` are excluded from that encumbrance total, which is precisely why a release raises availability. The three encumbered statuses are treated identically for availability purposes: moving an allocation from `RESERVED` to `COMMITTED`, and later from `COMMITTED` to `DISBURSED`, leaves the pool's `available_cents` untouched, because encumbered money is encumbered money whether it is merely promised, contractually committed, or actually paid out.

Reserving money is the `FinanceOfficer`'s act. The payload names the `pool_id`, a `purpose` of `TREATMENT` or `MAINTENANCE`, an `amount_cents` of at least 1 cent, and `expected_pool_version`. Exactly one link must accompany the purpose: `TREATMENT` requires a `proposal_id` with `visit_id` left null, and `MAINTENANCE` requires a `visit_id` with `proposal_id` left null. Supplying the wrong link, or both, or neither, is refused with `ERR_ALLOCATION_LINK_MISMATCH`; the identifier supplied must still resolve first, so a `visit_id` naming no visit answers `ERR_VISIT_NOT_FOUND` even on a `TREATMENT` reservation. Beyond resolving, neither the linked proposal's status nor the linked visit's status is inspected at reservation time, and the artwork behind either is not consulted at all. The requested `amount_cents` must not exceed the pool's `available_cents` at reservation time, failing which the request draws `ERR_POOL_FUNDS_INSUFFICIENT`. A successful reservation is created in `RESERVED` with `release_reason` of `NONE` and `released_at` null, `expected_pool_version` being consumed by the check rather than stored, lowers the pool's `available_cents` by `amount_cents`, and increments the pool's own `version` — which is what makes a second reservation from a stale read fail.

An allocation advances through the lifecycle of whatever it funds. Starting a treatment execution or starting a maintenance visit moves the linked allocation `RESERVED → COMMITTED`; completing either moves it `COMMITTED → DISBURSED`. `DISBURSED` and `RELEASED` are terminal.

Releasing is the compensating action for reserving, and the money invariant must hold again afterwards. A `FinanceOfficer` may release an allocation directly, with an optional `release_note`, but only while it sits in `RESERVED`; an attempt against any other status draws `ERR_ALLOCATION_INVALID_STATE`. A manual release stamps `release_reason` as `MANUAL_RELEASE`, stamps `released_at` from the logical clock, and raises the pool's `available_cents` by the allocation's `amount_cents`. Cascaded releases behave identically on the money side but stamp a different reason: `VISIT_ABORTED` where the funded visit was aborted, `PROPOSAL_WITHDRAWN` where the funded proposal was withdrawn by supersession or by deaccession, and `PROPOSAL_REJECTED` where the funded proposal was rejected outright. Cascades release from `RESERVED` and from `COMMITTED` alike; only a manual release is restricted to `RESERVED`.

### 3.11. Damage Response and Insurance Recovery

Damage is reported by a `CollectionsRegistrar`, a `PublicArtManager` or a `MaintenanceCrew` member. The report names the `artwork_id`, an `incident_type` of `GRAFFITI`, `VANDALISM`, `VEHICLE_IMPACT`, `WEATHER` or `THEFT`, a `damage_extent_pct` between 0.00 and 1.00 inclusive carried to two decimals expressing the fraction of the work's value impaired — the bound is enforced but the two-place presentation is not, so the value is stored exactly as supplied — and a `narrative` of record. Two optional links may be supplied at report time or filled in later: `linked_proposal_id`, naming the approved repair proposal a restoration claim will draw on, and `credited_pool_id`, naming the pool a settlement will be paid into. The incident is created with `damage_status` of `REPORTED`, `claim_status` of `NONE`, `triage_class` of `NONE`, `claim_basis` of `NONE`, both `claimed_gross_cents` and `settlement_cents` at zero, and `reported_at` stamped from the logical clock.

A `ChiefConservator` triages the incident, moving `damage_status` `REPORTED → TRIAGED` and setting `triage_class` from the request to `ROUTINE_MAINTENANCE`, `CONSERVATOR_TREATMENT` or `TOTAL_LOSS`, with an optional `triage_note`. The physical damage dimension then resolves through the treatment track and not through the claim: when the proposal named by `linked_proposal_id` completes, the incident moves `TRIAGED → RESOLVED`, entirely independently of whatever the insurer has or has not decided.

Filing a claim is the `FinanceOfficer`'s act and moves `claim_status` `NONE → FILED`. The payload names a `claim_basis` of `ACV` or `RESTORATION`, may supply or correct `credited_pool_id`, and may carry a `policy_note`. Filing requires the incident's `claim_status` to be `NONE` and its `damage_status` to be `TRIAGED` — an untriaged incident cannot be claimed — and the insurance dimension is inspected first, so an incident that is both already claimed and untriaged answers `ERR_CLAIM_INVALID_STATE` rather than `ERR_INCIDENT_INVALID_STATE`. A supplied `credited_pool_id` overwrites the one recorded at report time; omitting it leaves whatever was there. A `RESTORATION` basis additionally requires `linked_proposal_id` to be set, that proposal to be in `APPROVED`, `IN_EXECUTION` or `COMPLETED`, and its `pinned_estimate_total_cents` to be non-null; any of those missing yields `ERR_CLAIM_BASIS_UNSUPPORTED`.

The two bases compute a gross claim in entirely different ways, which is the point: identical incident data settles at different amounts depending on which basis the filer chooses. Under **actual cash value**, the work is written down for age. The elapsed days between the work's `acquisition_date` and the logical clock's date are divided by 365 and truncated down to a whole number of years, and that age is capped at 25 years. The depreciated value is the work's `insured_value_cents` multiplied by 0.98 raised to the power of that age in years, rounded half up to a whole cent. `claimed_gross_cents` is then that depreciated value multiplied by `damage_extent_pct`, rounded half up to a whole cent — note that the depreciation is rounded once before the extent multiplier is applied, and the product is rounded again after. Under **restoration**, `claimed_gross_cents` is simply the `pinned_estimate_total_cents` of the linked proposal, wholly independent of insured value, acquisition age and `damage_extent_pct`.

`settlement_cents` follows from the gross figure in both cases. The gross claim is first capped at the policy limit of 25,000,000 cents (250,000 dollars), the deductible of 250,000 cents (2,500 dollars) is then subtracted, and the result is floored at zero. A claim whose gross figure does not exceed the deductible therefore settles at zero.

Resolution is again the `FinanceOfficer`'s act and requires `claim_status` to be `FILED`. The payload carries an `outcome` of `SETTLE` or `DENY` and an optional `resolution_note`. A `SETTLE` moves `claim_status` `FILED → SETTLED` and requires two things: `settlement_cents` must be strictly greater than zero, so a claim computed down to nothing after limit and deductible cannot be settled and draws `ERR_NO_SETTLEMENT_PAYABLE`; and `credited_pool_id` must be non-null, failing which the request draws `ERR_CREDIT_POOL_REQUIRED`. On settlement the named pool's `recovery_credits_cents` rises by `settlement_cents` and its `available_cents` rises by the same amount, and the pool's `version` increments — which is exactly the kind of unrequested movement that makes the pool version check in §2.11 necessary. A `DENY` moves `claim_status` `FILED → DENIED`, sets `settlement_cents` to zero and credits no pool.

## 4. Endpoint Definitions

Operations that bring a new record into existence return `201 Created`. Every other operation — reads, state transitions, appends to a record's own internal collection such as a photograph or a cost line or a ballot, and the administrative capabilities — returns `200 OK`. All paths below are absolute; note that the clock capability sits outside the `/public-art` mount. Free-text notes and reference strings carried on transitions and appends — `surveyor_note`, `reviewer_note`, `finalization_note`, `completion_note`, `submitter_note`, `approval_note`, `rejection_reason`, `mobilization_note`, `completion_report_ref`, `acknowledgement_note`, `advance_note`, `ballot_note`, `execution_note`, `release_note`, `triage_note`, `policy_note`, `resolution_note`, `relocation_note`, a suspension's `reason` and a photograph's `media_ref` and `caption` — are validated for presence and type exactly as each section describes, and are then discarded rather than persisted on the target record or echoed in the response; the two exceptions are a consultation's `response_note` and a maintenance visit's `crew_note`, which are stored on their records.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/public-art/artists` | Register an artist of record | CollectionsRegistrar, PublicArtManager |
| GET | `/public-art/artists/{id}` | Read one artist | Any |
| GET | `/public-art/artists` | List artists | Any |
| POST | `/public-art/sites` | Register an installation site | CollectionsRegistrar, PublicArtManager |
| GET | `/public-art/sites/{id}` | Read one site including its installed footprint | Any |
| GET | `/public-art/sites` | List sites | Any |
| POST | `/public-art/artworks` | Accession an artwork into the collection at a site | CollectionsRegistrar |
| GET | `/public-art/artworks/{id}` | Read one artwork with both status dimensions, condition index and priority ranking | Any |
| GET | `/public-art/artworks` | List artworks | Any |
| POST | `/public-art/artworks/{id}/relocate` | Move a work into storage or reinstall it at a site | CollectionsRegistrar |
| POST | `/public-art/maintenance-protocols` | Declare a routine care protocol for a material | ChiefConservator, PublicArtManager |
| GET | `/public-art/maintenance-protocols/{id}` | Read one protocol | Any |
| GET | `/public-art/maintenance-protocols` | List protocols | Any |
| POST | `/public-art/conservators` | Register a conservation vendor | PublicArtManager |
| GET | `/public-art/conservators/{id}` | Read one conservator | Any |
| GET | `/public-art/conservators` | List conservators | Any |
| POST | `/public-art/conservators/{id}/suspend` | Suspend a vendor so no new proposal may be approved for them | PublicArtManager |
| POST | `/public-art/condition-assessments` | Open a condition survey in draft for one artwork in a cycle year | ConditionSurveyor |
| GET | `/public-art/condition-assessments/{id}` | Read one condition survey | Any |
| GET | `/public-art/condition-assessments` | List condition surveys | Any |
| POST | `/public-art/condition-assessments/{id}/photos` | Attach one photographic record to a draft or returned survey | ConditionSurveyor |
| POST | `/public-art/condition-assessments/{id}/submit` | Submit a survey for conservator review | ConditionSurveyor |
| POST | `/public-art/condition-assessments/{id}/request-revision` | Send a submitted survey back to the surveyor | ChiefConservator |
| POST | `/public-art/condition-assessments/{id}/finalize` | Finalize a survey; computes the condition index and runs Cascade A | ChiefConservator |
| POST | `/public-art/maintenance-visits` | Schedule a routine care visit in a site work window | MaintenanceCrew, ChiefConservator |
| GET | `/public-art/maintenance-visits/{id}` | Read one visit | Any |
| GET | `/public-art/maintenance-visits` | List visits | Any |
| POST | `/public-art/maintenance-visits/{id}/start` | Start a scheduled visit once its window has opened | MaintenanceCrew |
| POST | `/public-art/maintenance-visits/{id}/complete` | Complete a visit; evaluates the graffiti response window and the next due date | MaintenanceCrew |
| POST | `/public-art/treatment-proposals` | Draft a treatment proposal against a finalized survey | ChiefConservator |
| GET | `/public-art/treatment-proposals/{id}` | Read one proposal with its cost breakdown | Any |
| GET | `/public-art/treatment-proposals` | List proposals | Any |
| POST | `/public-art/treatment-proposals/{id}/line-items` | Append a cost line and recompute the estimate | ChiefConservator |
| POST | `/public-art/treatment-proposals/{id}/submit` | Submit a proposal for manager review | ChiefConservator |
| POST | `/public-art/treatment-proposals/{id}/request-revision` | Send a submitted proposal back for revision | PublicArtManager |
| POST | `/public-art/treatment-proposals/{id}/approve` | Approve a proposal; pins the estimate and runs Cascade C | PublicArtManager |
| POST | `/public-art/treatment-proposals/{id}/reject` | Reject a submitted proposal and release its funding | PublicArtManager |
| POST | `/public-art/treatment-proposals/{id}/start-execution` | Conservator starts the approved treatment | ConservatorVendor |
| POST | `/public-art/treatment-proposals/{id}/complete` | Conservator closes out the treatment | ConservatorVendor |
| POST | `/public-art/artist-consultations` | Open an artist consultation | ChiefConservator, PublicArtManager |
| GET | `/public-art/artist-consultations/{id}` | Read one consultation | Any |
| GET | `/public-art/artist-consultations` | List consultations | Any |
| POST | `/public-art/artist-consultations/{id}/respond` | Artist concurs with or objects to the consulted action | ArtistRepresentative |
| POST | `/public-art/moral-rights-notices` | Send a moral-rights notice starting the statutory waiting period | PublicArtManager, CollectionsRegistrar |
| GET | `/public-art/moral-rights-notices/{id}` | Read one notice | Any |
| GET | `/public-art/moral-rights-notices` | List notices | Any |
| POST | `/public-art/moral-rights-notices/{id}/acknowledge` | Artist acknowledges receipt of the notice | ArtistRepresentative |
| POST | `/public-art/deaccession-cases` | Open a deaccession case citing review criteria and a disposition | PublicArtManager |
| GET | `/public-art/deaccession-cases/{id}` | Read one case with its ballots and tally | Any |
| GET | `/public-art/deaccession-cases` | List cases | Any |
| POST | `/public-art/deaccession-cases/{id}/advance` | Open the public comment period, or move to board review once it has closed | PublicArtManager |
| POST | `/public-art/deaccession-cases/{id}/votes` | Cast one commission ballot; auto-tallies at quorum | ArtCommissionMember, PublicArtManager |
| POST | `/public-art/deaccession-cases/{id}/execute` | Execute an approved deaccession; runs Cascade B | PublicArtManager |
| POST | `/public-art/funding-pools` | Open a maintenance endowment or percent-for-art set-aside pool | FinanceOfficer |
| GET | `/public-art/funding-pools/{id}` | Read one pool with its authorized draw and current availability | FinanceOfficer, PublicArtManager, ChiefConservator |
| GET | `/public-art/funding-pools` | List pools | FinanceOfficer, PublicArtManager, ChiefConservator |
| POST | `/public-art/funding-allocations` | Reserve money from a pool for a treatment or a maintenance visit | FinanceOfficer |
| GET | `/public-art/funding-allocations/{id}` | Read one allocation | FinanceOfficer, PublicArtManager, ChiefConservator |
| GET | `/public-art/funding-allocations` | List allocations | FinanceOfficer, PublicArtManager, ChiefConservator |
| POST | `/public-art/funding-allocations/{id}/release` | Release a reserved allocation back to its pool | FinanceOfficer |
| POST | `/public-art/damage-incidents` | Report vandalism or damage to a work | CollectionsRegistrar, PublicArtManager, MaintenanceCrew |
| GET | `/public-art/damage-incidents/{id}` | Read one incident with both dimensions and the claim figures | Any |
| GET | `/public-art/damage-incidents` | List incidents | Any |
| POST | `/public-art/damage-incidents/{id}/triage` | Triage an incident onto a response route | ChiefConservator |
| POST | `/public-art/damage-incidents/{id}/file-claim` | File the insurance claim on an actual-cash-value or restoration basis | FinanceOfficer |
| POST | `/public-art/damage-incidents/{id}/resolve-claim` | Settle or deny a filed claim; a settlement credits the named pool | FinanceOfficer |
| POST | `/public-art/ops/run-cycle` | Cycle checkpoint: re-ranks the collection, lapses overdue consultations, elapses matured notices and returns stabilized works to monitoring | PublicArtManager |
| POST | `/_clock/set_current_utc` | Test-driving capability: set the logical clock | PublicArtManager |

"Any" above means all nine roles. Funding pool and funding allocation reads are the sole exception and are limited to the three roles named on their rows.

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_ARTIST_NOT_FOUND` | 404 Not Found |
| `ERR_SITE_NOT_FOUND` | 404 Not Found |
| `ERR_ARTWORK_NOT_FOUND` | 404 Not Found |
| `ERR_PROTOCOL_NOT_FOUND` | 404 Not Found |
| `ERR_VISIT_NOT_FOUND` | 404 Not Found |
| `ERR_ASSESSMENT_NOT_FOUND` | 404 Not Found |
| `ERR_CONSERVATOR_NOT_FOUND` | 404 Not Found |
| `ERR_PROPOSAL_NOT_FOUND` | 404 Not Found |
| `ERR_CONSULTATION_NOT_FOUND` | 404 Not Found |
| `ERR_NOTICE_NOT_FOUND` | 404 Not Found |
| `ERR_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_POOL_NOT_FOUND` | 404 Not Found |
| `ERR_ALLOCATION_NOT_FOUND` | 404 Not Found |
| `ERR_INCIDENT_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_ARTWORK_VERSION` | 412 Precondition Failed |
| `ERR_STALE_POOL_VERSION` | 412 Precondition Failed |
| `ERR_ASSESSMENT_INVALID_STATE` | 409 Conflict |
| `ERR_PROPOSAL_INVALID_STATE` | 409 Conflict |
| `ERR_VISIT_INVALID_STATE` | 409 Conflict |
| `ERR_CASE_INVALID_STATE` | 409 Conflict |
| `ERR_NOTICE_INVALID_STATE` | 409 Conflict |
| `ERR_CONSULTATION_INVALID_STATE` | 409 Conflict |
| `ERR_ALLOCATION_INVALID_STATE` | 409 Conflict |
| `ERR_INCIDENT_INVALID_STATE` | 409 Conflict |
| `ERR_CLAIM_INVALID_STATE` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 409 Conflict |
| `ERR_INITIATOR_CANNOT_VOTE` | 409 Conflict |
| `ERR_ARTWORK_DEACCESSIONED` | 409 Conflict |
| `ERR_ARTWORK_CUSTODY_INVALID` | 409 Conflict |
| `ERR_RECOGNIZED_STATURE_PROTECTED` | 422 Unprocessable Entity |
| `ERR_ARTIST_CONSULTATION_REQUIRED` | 422 Unprocessable Entity |
| `ERR_ARTIST_CONSULTATION_PENDING` | 409 Conflict |
| `ERR_ARTIST_OBJECTION_UNRESOLVED` | 409 Conflict |
| `ERR_MORAL_RIGHTS_NOTICE_REQUIRED` | 422 Unprocessable Entity |
| `ERR_MORAL_RIGHTS_WAIT_ACTIVE` | 409 Conflict |
| `ERR_CONSERVATOR_NOT_ELIGIBLE` | 422 Unprocessable Entity |
| `ERR_PROTOCOL_MATERIAL_MISMATCH` | 422 Unprocessable Entity |
| `ERR_PHOTO_DOCUMENTATION_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_WINDOW_IN_PAST` | 422 Unprocessable Entity |
| `ERR_VISIT_WINDOW_NOT_OPEN` | 409 Conflict |
| `ERR_PUBLIC_COMMENT_OPEN` | 409 Conflict |
| `ERR_CONSULTATION_WINDOW_CLOSED` | 409 Conflict |
| `ERR_DUPLICATE_CODE` | 409 Conflict |
| `ERR_CONSERVATOR_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_SITE_WORK_CAPACITY_CONFLICT` | 409 Conflict |
| `ERR_SITE_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_ACTIVE_PROPOSAL` | 409 Conflict |
| `ERR_ASSESSMENT_NOT_FINALIZED` | 422 Unprocessable Entity |
| `ERR_MAX_ANNUAL_APPLICATIONS` | 409 Conflict |
| `ERR_DUPLICATE_BALLOT` | 409 Conflict |
| `ERR_REVISION_LIMIT_REACHED` | 409 Conflict |
| `ERR_DISPOSITION_TARGET_REQUIRED` | 422 Unprocessable Entity |
| `ERR_ALLOCATION_LINK_MISMATCH` | 422 Unprocessable Entity |
| `ERR_CLAIM_BASIS_UNSUPPORTED` | 422 Unprocessable Entity |
| `ERR_CREDIT_POOL_REQUIRED` | 422 Unprocessable Entity |
| `ERR_POOL_FUNDS_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_FUNDING_NOT_RESERVED` | 422 Unprocessable Entity |
| `ERR_NO_SETTLEMENT_PAYABLE` | 422 Unprocessable Entity |
