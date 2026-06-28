# Pet DNA & Health Screening API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Pet DNA & Health Screening API, a back-end platform in the spirit of consumer canine and feline genetics services. The product takes a pet owner from the moment they order a sample-collection kit all the way through swab activation, laboratory receipt and genotyping, the production of a breed-ancestry and genetic-health report, and the optional discovery of genetic relatives across the customer base. Along the way it manages vet-shareable report links, paid subscriptions and upgrades, and the data-governance machinery that lets an owner export or permanently delete everything the platform knows about their pets.

The system coordinates four very different kinds of actor — the pet owner who buys and consumes the product, the laboratory operator who drives the wet-lab and bioinformatics pipeline, the veterinarian who reads a shared report, and the platform operator who runs catalog, clock, and privacy batch jobs. Because a single physical sample can fail and be re-tested, a report can be revised after preliminary issuance, and a deletion request triggers an irreversible cascade across many resources, the platform places strong emphasis on explicit state machines, deterministic calculations, and disciplined concurrency control. The sections that follow describe the global contract every endpoint honours, the business workflows that the domain entities move through, and the precise rules governing each transition, computation, and rejection.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response contracts, and cross-cutting principles that apply across the entire API. Unless a later workflow section narrows or overrides a behaviour, everything here is in force for every endpoint.

### 2.1. User and Role-Based Access Control

Every request to an authenticated endpoint must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. When either header is missing or malformed on an authenticated endpoint, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The platform recognises five roles, spelled exactly as follows: `PlatformAdmin`, `Account`, `LabTechnician`, `Veterinarian`, and `Anonymous`.

- When `X-User-Role` is `Account`, `X-User-ID` is the `id` of the acting `Account`; ownership checks on any resource that references an `Account` compare the resource's owning-account foreign key to `X-User-ID`. Because pets, kits, samples (via their kit), reports (via their pet), subscriptions, data requests, share links, and relative matches all chain back to an owning account, an `Account` acts only on resources that resolve to its own `id`. For a `RelativeMatch`, either pet's owner is treated as an authorised actor.
- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it but does not compare it to any entity's `id`.
- When `X-User-Role` is `LabTechnician`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; the lab role drives the genotyping pipeline and is not subject to account-ownership checks.
- When `X-User-Role` is `Veterinarian`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. A veterinarian's only capability is reading a report through a share token.
- When `X-User-Role` is `Anonymous`, `X-User-ID` is an opaque, unauthenticated identifier not tied to any persisted entity. Like the veterinarian, an anonymous holder may only read a shared report through its token.

A single endpoint — the token-based shared-report view — is public and requires no authentication headers at all; it is the only operation exempt from the `ERR_UNAUTHENTICATED` check. Every other endpoint requires both headers.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items are returned; it defaults to 10, may be no smaller than 1, and may be no larger than 100. The `offset` parameter is the number of items to skip from the start of the result set and defaults to 0.

Unless a specific endpoint states otherwise, every list endpoint returns its resources sorted by creation timestamp in ascending order — that is, by `created_at` ascending.

The response envelope's `meta` object on any list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the size of the full filtered set and `has_more` indicates whether further pages remain beyond the current window.

### 2.4. Common Resource Properties and the Logical Clock

Most resources in the system are full first-class entities and carry a standard set of system-managed fields. Accounts, pets, kits, samples, genotyping runs, reports, relative matches, share links, subscriptions, and data requests each expose:

- `id` — a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, fixed at the moment the resource is first created.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` — an integer that starts at its initial value on creation and increments by exactly one on every mutation of the resource. It is the basis for optimistic concurrency control.

Two entities are deliberately lighter. A `HealthMarkerResult` and a `MarkerCatalogEntry` are immutable append-only records; each carries only an `id` (UUID) and a `created_at` timestamp, and **neither** carries an `updated_at` field **nor** a `version` field. Any rule elsewhere in this document that speaks of bumping a `version` or refreshing `updated_at` applies only to the ten versioned entities and never to these two.

All temporal behaviour in the system is driven by a **logical clock**, never by wall-clock time. On server startup the clock reads exactly `2026-01-01T00:00:00Z`, and before any clock-setting call it stays at that default and never falls back to real time. A platform operator may advance the clock by supplying a target instant; the supplied value is provided in a field named `to_iso8601`. Every temporal computation in this document — grace windows, subscription term expiry, certification-style date comparisons — reads the current logical clock.

### 2.5. Precision and Rounding

Several computed values are decimals and must be produced with deterministic precision. The `qc_score` on a genotyping run and copied onto its sample, each breed-percentage in a report's `breed_composition`, and a relative match's `relationship_pct` are all carried to exactly two decimal places, using the round-half-up method on the final value. Monetary fields are integer cents and are never rounded to decimals: a subscription's `annual_fee_cents`, its `last_charge_cents`, and the proration arithmetic that produces them are all whole-cent integers, with any division flooring to the nearest whole cent as described in the subscription workflow. Counts such as a report's `at_risk_marker_count` and an account's `pet_count` are plain integers.

### 2.6. Hierarchical Consistency and Cascades

The system maintains immediate, hierarchical consistency: whenever an operation changes one resource in a way that affects another, the dependent resource is reconciled within the same operation rather than left to drift. Several workflows in §3 describe cascades in which a single request mutates multiple resources at once — a passing genotyping run that simultaneously consumes a kit and creates a report, a report revocation that revokes share links and recomputes a pet's back-pointer, a deletion purge that archives pets and tears down their downstream resources, and an opt-out that withdraws outstanding matches. In every such cascade, each resource the system touches is independently mutated: its `updated_at` is refreshed and its `version` is incremented by one (subject to the exemption in §2.4 for the two version-less entities). The denormalised back-pointer fields — an account's `active_subscription_id` and `pet_count` and `purge_pending`, a pet's `finalized_report_id`, a kit's `activated_pet_id`, a sample's `pet_id` and `qc_score`, a report's `pet_id` and `includes_health` — are kept reconciled as the events that govern them occur, and may always be re-derived by listing the relevant collection as their field descriptions indicate.

### 2.7. Nested Resource Retrieval and Existence Ordering

The entity model is flat: resources are peer collections linked by foreign-key fields carried in request bodies, not by deep URL nesting. A handful of endpoints do address a child collection through a parent identifier in the path (for example, the genotyping runs and markers that hang off a sample or a report). For any request that names more than one resource — whether in the path or in the body — the server validates existence left to right and rejects the first referent that does not exist with `ERR_NOT_FOUND`. This existence check runs after authentication and role authorisation but before business-rule evaluation, so a request that names a missing resource never reaches the deeper state and ownership checks.

### 2.8. Validation Ordering

When several checks could fail on one request, they are evaluated in a fixed priority order so that the returned error is deterministic. The order is: first, authentication of the `X-User-ID` and `X-User-Role` headers (`ERR_UNAUTHENTICATED`); second, role authorisation against the operation (`ERR_FORBIDDEN_ROLE`); third, existence of every referenced resource, left to right (`ERR_NOT_FOUND`); fourth, ownership — that the acting account owns the targeted resource (`ERR_NOT_RESOURCE_OWNER`); fifth, that the target resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`). After these five framework checks, the business rules specific to each operation apply, themselves ordered: the relative-match cross-entity finalized-report precondition (`ERR_REPORTS_NOT_FINALIZED`); the relative-finder opt-in requirement (`ERR_RELATIVE_FINDER_NOT_OPTED_IN`); the purge-in-progress freeze (`ERR_PURGE_IN_PROGRESS`); re-test eligibility (`ERR_RETEST_NOT_ELIGIBLE`); sample genotypability (`ERR_SAMPLE_NOT_GENOTYPABLE`); the single-subscription rule (`ERR_SUBSCRIPTION_EXISTS`); the temporal-window checks for purge and expire (`ERR_GRACE_NOT_ELAPSED`); numeric range checks (`ERR_INVALID_RANGE`); the health-section gate on markers (`ERR_HEALTH_NOT_INCLUDED`); presence of required body fields and valid enum values (`ERR_INVALID_REQUEST`); and the optimistic-concurrency version check (`ERR_STALE_VERSION`). Where a single operation is guarded by several of these, the earlier-listed check is the one whose error surfaces first.

### 2.9. Optimistic Concurrency Control

Two mutating operations are guarded by optimistic concurrency control, and both require the client to declare the version it last observed on the parent resource.

The first is the subscription upgrade. A request to upgrade a subscription must carry `expected_subscription_version`, and this value must equal the target subscription's current `version`. If another writer has advanced that subscription's `version` since the client last read it — for instance because the subscription was already cancelled, moving it from `ACTIVE` to `GRACE`, or already upgraded, moving it from `ACTIVE` to `SUPERSEDED` — then the upgrade is acting on a stale view and is rejected with `ERR_STALE_VERSION` (HTTP 412). The field is mandatory; an upgrade without it is rejected as an invalid request.

The second is report finalization. A request to finalize a report must carry `expected_report_version` matching the target report's current `version`. Because attaching a reviewed marker or revoking the report bumps its `version`, a finalize that carries an out-of-date version is operating on a stale report view and is rejected with `ERR_STALE_VERSION` (HTTP 412). This field too is mandatory. No other endpoint takes a version field, and operations not named here perform no version check.

## 3. Business Logic & Workflows

### 3.1. Accounts, Pets, and the Relative-Finder Opt-In

Everything in the platform hangs off an **Account**. Only a platform operator may register an account, supplying the account's login `email` — which must be non-empty and unique across all accounts — and the holder's `full_name`. Two further fields are optional at registration: `data_residency`, which is one of `US` or `EU` and defaults to `US` when omitted, governing the export-and-delete regime that applies to the account; and `relative_finder_opt_in`, a boolean master switch for the genetic-relative network that defaults to `false`. An account also exposes several read-only computed fields. Its `active_subscription_id` denormalises the id of the account's current subscription whose status is either `ACTIVE` or `GRACE`, and is null when no such subscription exists. Its `pet_count` is the number of the account's pets whose status is not `ARCHIVED`. Its `purge_pending` flag is true exactly while the account has a deletion-type data request sitting in `GRACE` or `PURGING`.

A **Pet** is registered by its owning account, which supplies the pet's `account_id`, its `name`, its `species` (one of `DOG` or `CAT`), and its `birth_year`, which is retained only for display. A pet may also be given a per-pet `relative_finder_opt_in`, again defaulting to `false`. On registration the pet enters the `REGISTERED` state — the value of its system-managed `status`, which is one of `REGISTERED` or `ARCHIVED` — and registering a pet increments the owning account's `pet_count`. A pet also carries a computed `finalized_report_id`, the id of the pet's most recent finalized report (the latest by creation timestamp, with the last one winning), or null when the pet has no finalized report. A pet is never archived directly; archival happens only as a downstream cascade of an account deletion, described in §3.8.

The relative-finder network is governed by two switches that must both be on. The account-level switch is updated through an account update that accepts a new `relative_finder_opt_in` value, and the per-pet switch is updated through a pet update that accepts a new `relative_finder_opt_in` value. Turning the per-pet switch off has a consequence: every `ESTIMATED` relative match that references that pet is automatically withdrawn, moving each such match from `ESTIMATED` to `WITHDRAWN` and incrementing its `version`. The account-level switch behaves the same way when set to false — outstanding `ESTIMATED` matches of the account's pets auto-withdraw. A pet may participate in the relative-finder network — be matched or queried into it — only when both its owning account's `relative_finder_opt_in` and its own `relative_finder_opt_in` are true; an attempt to create a match where either pet fails this two-level check is rejected with `ERR_RELATIVE_FINDER_NOT_OPTED_IN`.

### 3.2. Ordering and Activating a Kit

A pet owner buys a **Kit** by ordering one for their account, supplying the `account_id` and the `product_tier`, which is one of `BREED` or `BREED_HEALTH`. The product tier gates which report sections will eventually be produced: only a `BREED_HEALTH` kit unlocks the genetic-health marker section. On creation the server mints a unique `barcode` used later for swab activation, and the kit enters the `ORDERED` state — its `status` being one of `ORDERED`, `ACTIVATED`, `RECEIVED`, `CONSUMED`, or `VOIDED`. A kit also carries a computed `activated_pet_id`, which is null until the swab is activated against a pet.

Activation is the owner's act of binding the kit's swab to a specific pet. Activating a kit advances it from `ORDERED` to `ACTIVATED` and requires a `pet_id` in the request body. The activation is permitted only when the kit is currently `ORDERED`, the named pet exists and belongs to the same account that owns the kit, the pet's `status` is `REGISTERED`, and the account is not currently frozen by a pending deletion (its `purge_pending` is false). When these hold, the system sets the kit's `activated_pet_id` to the supplied `pet_id` and increments the kit's `version`. Should the owner change their mind before activating, an un-activated kit may be voided, moving it from `ORDERED` to `VOIDED` and incrementing its `version`; only a kit still in `ORDERED` may be voided, and an attempt to void a kit in any other state is rejected as an invalid state transition with `ERR_INVALID_STATE`.

### 3.3. Sample Receipt, the Genotyping Pipeline, and Re-Tests

When the physical swab arrives at the lab, a lab operator records its receipt against the activated kit. Receiving a sample is done by supplying the `kit_id` of the activated kit; this is allowed only while the kit is `ACTIVATED`. Receipt creates a **Sample** in the `RECEIVED` state — its `status` is one of `RECEIVED`, `GENOTYPING`, `PASS`, `QNS`, `FAILED`, or `RETESTED` — with its `kit_id` set and its computed `pet_id` copied from the kit's `activated_pet_id`, and it advances the kit from `ACTIVATED` to `RECEIVED`, incrementing the kit's `version`. A sample also carries a computed `qc_score` (two decimals, null until a run completes) and a `retest_of_sample_id` foreign key that is null for a first sample.

The lab drives genotyping by creating a **GenotypingRun** against a sample. A run accepts three quality metrics — `call_rate` (the fraction of markers successfully called), `het_rate` (the observed heterozygosity rate), and `contamination` (the estimated cross-sample contamination fraction) — and may optionally carry a `breed_segments` array used later for ancestry. Each of the three metrics must lie between 0 and 1 inclusive; a value outside that range is rejected with `ERR_INVALID_RANGE`. A run may be created only on a sample whose `status` is `RECEIVED` or `GENOTYPING`, and the same kit may not hold two non-terminal samples at once; a run requested against a sample in any other state, or a second live sample on the same kit, is rejected with `ERR_SAMPLE_NOT_GENOTYPABLE`. The first run created against a `RECEIVED` sample advances it from `RECEIVED` to `GENOTYPING` and increments the sample's `version`.

Each run immediately computes a `qc_score` and an `outcome`. The score is a weighted blend, expressed on a 0-to-100 scale. First, a heterozygosity-consistency term is formed: take the absolute difference between `het_rate` and the target heterozygosity of 0.35, divide that difference by 0.35, subtract the result from 1, and clamp the outcome to the range 0 through 1. The raw score is then 100 multiplied by the sum of three weighted contributions — the call rate weighted by 0.6, one minus the contamination weighted by 0.3, and the heterozygosity-consistency term weighted by 0.1. The `qc_score` is that raw value rounded half-up to two decimal places. The `outcome`, one of `PASS`, `QNS`, or `FAILED`, is then decided in a fixed order: if `call_rate` is below the call-rate gate of 0.85 the outcome is `FAILED` and no further test is applied; otherwise, if the `qc_score` is below the QNS floor of 60.00 the outcome is `QNS`; otherwise the outcome is `PASS`. The call-rate gate is therefore evaluated before the QNS floor, so a sample with an adequate score but a deficient call rate still fails. Equivalently: a `call_rate` of at least 0.85 together with a `qc_score` of at least 60.00 yields `PASS`; a `call_rate` of at least 0.85 with a `qc_score` below 60.00 yields `QNS`; and a `call_rate` below 0.85 yields `FAILED` regardless of score. The computed `qc_score` and `outcome` are recorded on the run.

The run's outcome immediately drives the sample's fork, with the run's `qc_score` copied onto the sample's `qc_score` in every branch. On a `PASS` outcome the sample advances from `GENOTYPING` to `PASS`; this success path also transitions the owning kit from `RECEIVED` to `CONSUMED`, creates a `PRELIMINARY` report for the sample, and increments the sample's `version` (the kit's and report's versions follow their own creation and transition). On a `QNS` outcome — quantity not sufficient — the sample moves from `GENOTYPING` to `QNS`, copies the score, and increments its `version`, producing no report but leaving the sample eligible for a re-test. On a `FAILED` outcome the sample moves from `GENOTYPING` to `FAILED`, copies the score, and increments its `version`, likewise eligible for a re-test. The `PASS` state and the `RETESTED` state are terminal for a sample.

A re-test replaces a sample that did not yield a usable result. A re-test is created exactly like an ordinary receipt — by posting a sample — but with `retest_of_sample_id` pointing at the prior sample it replaces. The referenced sample may only be one whose `status` is `QNS` or `FAILED`; pointing a re-test at a `PASS` or `RECEIVED` sample (or any other state) is rejected with `ERR_RETEST_NOT_ELIGIBLE`. A re-test is further permitted only while the owning kit is back in `RECEIVED`. Creating the re-test marks the prior sample `RETESTED` (advancing it from `QNS` to `RETESTED`, or from `FAILED` to `RETESTED`) and creates a successor sample in `RECEIVED` on the same kit, incrementing the prior sample's `version`.

### 3.4. Building, Finalizing, and Revoking a Report

A **Report** is born the moment a sample passes genotyping. It is created in `PRELIMINARY` — its `status` is one of `PRELIMINARY`, `FINALIZED`, or `REVOKED` — with its `sample_id` set to the passing sample, its computed `pet_id` copied from that sample's `pet_id`, and a computed `includes_health` flag that is true exactly when the originating kit's `product_tier` was `BREED_HEALTH`. A report also carries a computed `breed_composition` array and an integer `at_risk_marker_count`.

The breed-ancestry composition is computed from the `breed_segments` array supplied on the passing genotyping run, each element of which carries a `breed` and a `match_cm`. First the total is formed by summing `match_cm` across all segments. Then, processing the segments in the order they appear in the request array, each segment's raw percentage is its `match_cm` divided by that total, multiplied by 100, rounded half-up to two decimal places. Because independent rounding rarely sums to exactly one hundred, a remainder is computed as 100.00 minus the sum of the rounded percentages, rounded half-up to two decimals, and that entire remainder is added to the single segment with the largest `match_cm` (ties broken in favour of the earliest array index). The resulting `breed_composition` is the list of `breed`-and-`pct` pairs in the original request order, and it sums to exactly 100.00. An empty `breed_segments` array yields an empty composition.

The genetic-health section is populated only on a report whose originating kit was `BREED_HEALTH`. A lab operator attaches a **HealthMarkerResult** to a report by supplying a `marker_code` drawn from the catalog, a `genotype` that is one of `CLEAR`, `CARRIER`, or `AT_RISK`, and optionally a `review_status`. The marker result's own `review_status` is one of `PASS` or `REVIEWED` and defaults to `PASS`. It also records the `report_id` it belongs to. Attaching a marker to a report whose kit was only `BREED` — that is, whose `includes_health` is false — is rejected with `ERR_HEALTH_NOT_INCLUDED`. Each marker attachment recomputes the report's `at_risk_marker_count` using the preliminary rule and increments the report's `version`.

The `at_risk_marker_count` is a count of the report's at-risk markers, but which markers count depends on the report's state. While the report is `PRELIMINARY`, the count includes only those marker results whose `genotype` is `AT_RISK` and whose `review_status` is `PASS`; reviewed markers are excluded. Once the report is `FINALIZED`, the count includes every marker result whose `genotype` is `AT_RISK` and whose `review_status` is either `PASS` or `REVIEWED`. Because finalization widens the filter to admit reviewed markers, the same underlying marker data can yield a higher count after finalization than before.

Finalizing a report is a lab operator's act that advances it from `PRELIMINARY` to `FINALIZED`. It is permitted only when the report is `PRELIMINARY`, the report's sample is in `PASS`, and the `breed_composition` has been computed and sums to 100.00. Finalization carries `expected_report_version` and is rejected with `ERR_STALE_VERSION` if that value does not match the report's live `version`, as described in §2.9. On success the system recomputes `at_risk_marker_count` under the finalized rule (now including reviewed markers), sets the report's pet's `finalized_report_id` to this report's id, and increments the report's `version`.

A report may be revoked by its owning account from either `PRELIMINARY` or `FINALIZED`, moving it to the terminal `REVOKED` state. Revocation cascades: every `ACTIVE` share link for the report is revoked, moving each from `ACTIVE` to `REVOKED`. When the revoked report is the one currently recorded in its pet's `finalized_report_id`, that back-pointer is recomputed to the next-most-recent finalized report for the pet, or set to null if none remains. Revocation increments the report's `version`.

### 3.5. Sharing a Report With a Veterinarian

An account may issue a **ShareLink** so a veterinarian can read one of its reports. Issuing a link supplies the `report_id` to be shared and the `vet_email` it is addressed to; the server mints a unique, opaque `token` and the link is created in the `ACTIVE` state — its `status` being one of `ACTIVE` or `REVOKED`. The token is the credential a vet uses to fetch the report without any authentication headers: the public shared-report view accepts a token and returns the underlying report, and it is the one endpoint open to the `Veterinarian` and `Anonymous` roles. If the token does not correspond to any link, or the link it names has been revoked, the lookup is rejected with `ERR_INVALID_TOKEN`.

The owning account may revoke an `ACTIVE` share link directly, moving it from `ACTIVE` to `REVOKED` and incrementing its `version`; only the account that owns the report's pet may do so, and the link must be `ACTIVE`. Share links are also revoked indirectly: when the underlying report is revoked, every `ACTIVE` link for it is swept to `REVOKED` as part of that cascade, and when an account deletion purges a pet, the `ACTIVE` links of that pet's reports are revoked as well.

### 3.6. The Relative-Finder Network

A **RelativeMatch** is the junction between two pets that share DNA. A lab operator creates a match by supplying the querying `pet_id`, the matched `relative_pet_id`, and the `shared_cm` — the shared autosomal centimorgans between the two genotypes, which must lie between 0 and 2500 inclusive, with values outside that range rejected by `ERR_INVALID_RANGE`. Both pets must satisfy the two-level relative-finder opt-in described in §3.1, or the create is rejected with `ERR_RELATIVE_FINDER_NOT_OPTED_IN`. A new match is created in the `ESTIMATED` state — its `status` being one of `ESTIMATED`, `CONFIRMED`, or `WITHDRAWN` — and the match also carries a computed `relationship_pct` to two decimals.

The kinship percentage is computed in one of two variants. At creation, the estimated variant is used: `relationship_pct` is `shared_cm` divided by the total autosomal length of 2500.0, multiplied by 100, rounded half-up to two decimals. When a match is later confirmed, the confirmed variant applies a phasing correction: `relationship_pct` is `shared_cm` multiplied by the phasing factor of 0.98, divided by 2500.0, multiplied by 100, and rounded half-up to two decimals. Because the phasing factor is below one, the confirmed percentage is lower than the estimated percentage for the same `shared_cm`.

Confirming a match is a lab operator's act that moves it from `ESTIMATED` to `CONFIRMED` and recomputes `relationship_pct` under the confirmed variant. Confirmation is permitted only when the match is `ESTIMATED` and both referenced pets have a finalized report — that is, both pets' `finalized_report_id` are non-null. A confirm attempted before both pets are finalized is rejected with `ERR_REPORTS_NOT_FINALIZED`. Confirmation increments the match's `version`.

A match may be withdrawn by the account that owns either of its pets, from `ESTIMATED` or from `CONFIRMED`, moving it to the terminal `WITHDRAWN` state and incrementing its `version`; the actor must own either the `pet_id` or the `relative_pet_id`. As described in §3.1, a match in `ESTIMATED` is also withdrawn automatically when a referenced pet's relative-finder opt-in is switched off, again moving it to `WITHDRAWN` and incrementing its `version`.

### 3.7. Subscriptions, Upgrades, and Expiry

An account may hold a paid **Subscription**, created by supplying the `account_id`, the `tier` (one of `BASIC` or `PREMIUM`), and the `annual_fee_cents` for that tier, which must be at least 0. A new subscription begins in `ACTIVE` — its `status` being one of `ACTIVE`, `GRACE`, `CANCELLED`, or `SUPERSEDED` — with its `started_on` set to the current logical clock, a `term_days` defaulting to 365, and its `last_charge_cents` set equal to the `annual_fee_cents` charged at creation. Creating the subscription sets the account's `active_subscription_id` to the new subscription. An account may hold only one subscription that is `ACTIVE` or `GRACE` at a time; a second create while such a subscription exists is rejected with `ERR_SUBSCRIPTION_EXISTS`.

An account may upgrade a subscription from `BASIC` to `PREMIUM`. The upgrade is allowed only when the subscription is `ACTIVE`, its current `tier` is `BASIC`, and the requested tier is `PREMIUM`; an upgrade on a non-`BASIC` subscription, or one requesting any tier other than `PREMIUM`, is rejected with `ERR_UPGRADE_NOT_ALLOWED`. The upgrade carries `expected_subscription_version` and is rejected with `ERR_STALE_VERSION` on a version mismatch, per §2.9. On success the original subscription moves from `ACTIVE` to `SUPERSEDED`, a successor subscription is created at tier `PREMIUM` in `ACTIVE` status with a prorated `last_charge_cents`, the account's `active_subscription_id` is repointed to the successor, and the superseded subscription's `version` is incremented.

The successor's prorated charge credits the unused portion of the basic term. The elapsed days are the whole number of days from the basic subscription's `started_on` date to the current logical-clock date, taking the floor. The remaining days are the basic subscription's `term_days` minus those elapsed days, which lies between 0 and `term_days`. The unused credit in cents is the basic subscription's `annual_fee_cents` multiplied by the remaining days, divided by the basic `term_days`, floored to a whole cent. The successor's `last_charge_cents` is the premium annual fee of 19900 cents minus that unused credit. If the unused credit would exceed the premium annual fee, the charge floors at 0 and never goes negative.

Cancelling a subscription moves it from `ACTIVE` to `GRACE` and increments its `version`; access is retained through `GRACE` until the term ends. Once the logical clock reaches or passes the subscription's `started_on` plus its `term_days` while the subscription is in `GRACE`, a platform operator may expire it, moving it from `GRACE` to `CANCELLED`, clearing the account's `active_subscription_id` to null, and incrementing its `version`. An expire requested before the clock has reached `started_on` plus `term_days` is rejected with `ERR_GRACE_NOT_ELAPSED`. The `CANCELLED` and `SUPERSEDED` states are terminal for a subscription.

### 3.8. Data Export, Deletion, and the Purge Cascade

An account governs its own data through a **DataRequest**, created by supplying the `account_id` and the `kind`, which is one of `DOWNLOAD` or `DELETE`. A request begins in `PENDING` — its `status` being one of `PENDING`, `READY`, `GRACE`, `PURGING`, `PURGED`, or `CANCELLED` — and carries a computed `grace_until` instant and a computed `export_payload` object.

A `DOWNLOAD` request auto-advances from `PENDING` to `READY` on creation, assembling an `export_payload` bundle from the account's pets, reports, and matches; for a download the `grace_until` is null. A `DELETE` request instead opens a cool-off: it advances from `PENDING` to `GRACE`, sets `grace_until` to the current logical clock plus 30 days, sets the account's `purge_pending` to true, and leaves `export_payload` null. A deletion may be opened only when no other data request for the account is already in `GRACE` or `PURGING`.

While a deletion request holds the account in `purge_pending`, the account and its pets are frozen against new mutations. Specifically, four operations are blocked while `purge_pending` is true — activating a kit, creating a relative match, creating a subscription, and issuing a share link — each rejected with `ERR_PURGE_IN_PROGRESS`. The single exception is that the account may always cancel the pending deletion itself.

Cancelling a deletion during the cool-off rescinds it, moving the request from `GRACE` to `CANCELLED`, clearing the account's `purge_pending` back to false, and incrementing the request's `version`. Otherwise, once the logical clock reaches or passes `grace_until`, a platform operator may advance the deletion from `GRACE` to `PURGING`, incrementing its `version`; a purge requested before the clock reaches `grace_until` is rejected with `ERR_GRACE_NOT_ELAPSED`. From `PURGING`, the operator finalizes the purge, moving the request from `PURGING` to the terminal `PURGED`. The purge-finalize is the irreversible cascade: every pet on the account is archived (each moving from `REGISTERED` to `ARCHIVED`, decrementing the account's `pet_count` and incrementing each pet's `version`), every `ACTIVE` share link of those pets' reports is revoked, and every `ESTIMATED` or `CONFIRMED` relative match referencing those pets is withdrawn. The cascade also clears the account's `purge_pending` to false and increments the request's `version`. The `PURGED` and `CANCELLED` states are terminal for a data request.

### 3.9. The Marker Catalog

The platform operator maintains the **MarkerCatalogEntry** dictionary that defines which genetic markers exist. Registering a catalog entry supplies a unique `marker_code`, a `category` that is one of `HEALTH` (a clinical health risk) or `TRAIT` (a phenotypic trait), and the `species` the marker applies to, one of `DOG` or `CAT`. Catalog entries are immutable reference records carrying only an `id` and `created_at`. A lab operator consults the catalog when attaching marker results to reports, and the catalog may be listed and filtered by `species` or `category`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including state-transition actions and the logical-clock setter — return a `200 OK` status code. The request body, response body, and side effects of each operation are described in the §3 workflow narratives; the table below summarises only the routing and authorisation contract.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/dna/_clock/set_current_utc` | Set the logical clock | PlatformAdmin |
| POST | `/dna/accounts` | Register an account | PlatformAdmin |
| GET | `/dna/accounts/{id}` | Fetch an account | PlatformAdmin, Account |
| PATCH | `/dna/accounts/{id}` | Update account-level relative-finder opt-in | Account |
| POST | `/dna/pets` | Register a pet | Account |
| GET | `/dna/pets/{id}` | Fetch a pet | PlatformAdmin, Account |
| GET | `/dna/pets` | List pets, optionally by account | PlatformAdmin, Account |
| PATCH | `/dna/pets/{id}` | Update per-pet relative-finder opt-in | Account |
| POST | `/dna/kits` | Order a kit | Account |
| GET | `/dna/kits/{id}` | Fetch a kit | PlatformAdmin, Account, LabTechnician |
| GET | `/dna/kits` | List kits | PlatformAdmin, Account |
| POST | `/dna/kits/{id}/activate` | Activate a kit against a pet | Account |
| POST | `/dna/kits/{id}/void` | Void an un-activated kit | Account |
| POST | `/dna/samples` | Receive a sample or create a re-test | LabTechnician |
| GET | `/dna/samples/{id}` | Fetch a sample | PlatformAdmin, Account, LabTechnician |
| GET | `/dna/samples` | List samples | PlatformAdmin, LabTechnician |
| POST | `/dna/samples/{id}/genotyping-runs` | Create a genotyping run | LabTechnician |
| GET | `/dna/samples/{id}/genotyping-runs` | List genotyping runs for a sample | PlatformAdmin, LabTechnician |
| GET | `/dna/reports/{id}` | Fetch a report | PlatformAdmin, Account, LabTechnician |
| GET | `/dna/reports` | List reports | PlatformAdmin, Account, LabTechnician |
| POST | `/dna/reports/{id}/markers` | Attach a marker result to a report | LabTechnician |
| GET | `/dna/reports/{id}/markers` | List marker results for a report | PlatformAdmin, Account, LabTechnician |
| POST | `/dna/reports/{id}/finalize` | Finalize a report | LabTechnician |
| POST | `/dna/reports/{id}/revoke` | Revoke a report | Account |
| POST | `/dna/share-links` | Issue a share link | Account |
| GET | `/dna/share-links/{id}` | Fetch a share link by id | PlatformAdmin, Account |
| GET | `/dna/share-links` | List share links | PlatformAdmin, Account |
| GET | `/dna/shared-reports/{token}` | Fetch a shared report by token | Veterinarian, Anonymous |
| POST | `/dna/share-links/{id}/revoke` | Revoke a share link | Account |
| POST | `/dna/relative-matches` | Create a relative match | LabTechnician |
| GET | `/dna/relative-matches/{id}` | Fetch a relative match | PlatformAdmin, Account, LabTechnician |
| GET | `/dna/relative-matches` | List relative matches | PlatformAdmin, Account, LabTechnician |
| POST | `/dna/relative-matches/{id}/confirm` | Confirm a relative match | LabTechnician |
| POST | `/dna/relative-matches/{id}/withdraw` | Withdraw a relative match | Account |
| POST | `/dna/subscriptions` | Create a subscription | Account |
| GET | `/dna/subscriptions/{id}` | Fetch a subscription | PlatformAdmin, Account |
| GET | `/dna/subscriptions` | List subscriptions | PlatformAdmin, Account |
| POST | `/dna/subscriptions/{id}/upgrade` | Upgrade BASIC to PREMIUM | Account |
| POST | `/dna/subscriptions/{id}/cancel` | Cancel a subscription | Account |
| POST | `/dna/subscriptions/{id}/expire` | Expire a grace subscription | PlatformAdmin |
| POST | `/dna/data-requests` | Open an export or deletion request | Account |
| GET | `/dna/data-requests/{id}` | Fetch a data request | PlatformAdmin, Account |
| GET | `/dna/data-requests` | List data requests | PlatformAdmin, Account |
| POST | `/dna/data-requests/{id}/purge` | Advance a deletion to purging | PlatformAdmin |
| POST | `/dna/data-requests/{id}/purge-finalize` | Execute the purge cascade | PlatformAdmin |
| POST | `/dna/data-requests/{id}/cancel` | Rescind a deletion during cool-off | Account |
| POST | `/dna/marker-catalog` | Register a marker catalog entry | PlatformAdmin |
| GET | `/dna/marker-catalog` | List marker catalog entries | PlatformAdmin, LabTechnician |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_REPORTS_NOT_FINALIZED` | 409 |
| `ERR_RELATIVE_FINDER_NOT_OPTED_IN` | 422 |
| `ERR_PURGE_IN_PROGRESS` | 409 |
| `ERR_RETEST_NOT_ELIGIBLE` | 422 |
| `ERR_SAMPLE_NOT_GENOTYPABLE` | 422 |
| `ERR_SUBSCRIPTION_EXISTS` | 409 |
| `ERR_GRACE_NOT_ELAPSED` | 409 |
| `ERR_INVALID_RANGE` | 422 |
| `ERR_HEALTH_NOT_INCLUDED` | 422 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_TOKEN` | 404 |
| `ERR_UPGRADE_NOT_ALLOWED` | 422 |
