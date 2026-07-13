# Online Reputation Management API — Product Requirements Document

## 1. Introduction

Multi-location brands live and die by what strangers say about them on Google, Yelp and Facebook. Today that conversation is fragmented: a franchise operator with forty storefronts has forty separate site dashboards, no consistent way to ask happy customers for a review, no audit trail over who wrote the reply that went out under the brand's name, and no early warning when a location's listing data quietly drifts out of sync with reality. The Online Reputation Management API exists to collapse that fragmentation into a single tenant-scoped system of record.

The platform serves four operational jobs at once. It runs **review-request campaigns** over SMS and email against a consented contact list, metering them with credits, daily send caps and a per-contact cooldown so that outreach never becomes spam. It **aggregates reviews** from the three supported external sites, scores their sentiment, and raises escalations on the negative ones. It governs a **reply workflow** under strict segregation of duties: the person who drafts a public response is never the person who approves it. And it maintains a **listing/NAP sync** loop that pushes each location's canonical Name-Address-Phone record out to the sites and penalises any listing that has drifted, gone stale, or failed to sync.

Binding these four together is a single derived gate called the location **posture**. Posture is not something an operator sets; it is recomputed by the server from the location's reputation score, its open escalation load, its listing health, and any compliance hold placed on it by the platform. A location whose posture degrades stops being able to activate campaigns and publish widgets, and any campaign already running is paused out from under it. The requirements below define that machinery precisely: the entities, the state machines, the scoring formulas, the ordering of validations, and the exact error each rejection carries. All resources described here are mounted under the `/reputation` prefix.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which declares the capacity in which it is acting. Six roles exist and their spellings are exact: `PlatformAdmin`, `BusinessOwner`, `LocationManager`, `ResponseAgent`, `ComplianceOfficer`, and `Anonymous`. If either header is absent, or if `X-User-Role` is not one of those six strings, the request is rejected with `ERR_UNAUTHENTICATED` (401). The one exception is the public surface: endpoints whose authorized-role list includes `Anonymous` accept a request that carries `X-User-Role: Anonymous` with no `X-User-ID` at all. A role that is not listed among the target endpoint's authorized roles is rejected with `ERR_UNAUTHORIZED` (403).

The meaning of `X-User-ID` depends on the role, and two of the six roles bind it to a persisted entity:

- When `X-User-Role` is `BusinessOwner`, `X-User-ID` is the `id` of the acting `Business`. Ownership checks on any resource that hangs beneath a business — a location, a contact, a template, and by extension everything under a location — compare the owning business's `id` to `X-User-ID` by walking the parent chain from the target resource up through `Location` to `Business`.
- When `X-User-Role` is `LocationManager`, `X-User-ID` is the `id` of the acting `Location`. Ownership checks on any resource that hangs beneath a location — listings, campaigns, review requests, reviews, responses, escalations, surveys, competitors, the widget — compare the owning location's `id` to `X-User-ID`.
- A mismatch in either case is a tenancy violation and is rejected with `ERR_CROSS_TENANT_ACCESS` (403). This check runs on every endpoint whose authorized-role list contains `BusinessOwner` or `LocationManager`.
- When `X-User-Role` is `PlatformAdmin`, `ResponseAgent`, `ComplianceOfficer`, or `Anonymous`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server may record it — for example as `drafted_by_user_id` and `approved_by_user_id` on a `ReviewResponse`, or as `acknowledged_by_user_id` on an `Escalation` — but it never compares it to any entity's `id`.

`PlatformAdmin` is a superset role: it may perform every operation in this specification, and it exclusively owns the connector and operational surfaces (tenant registration, compliance holds, site-connector review ingest, delivery-connector callbacks, and the logical clock). Superset status does not, however, exempt it from segregation of duties: a `PlatformAdmin` who drafted a response still cannot approve or reject that same response. `ResponseAgent` and `ComplianceOfficer` are deliberately disjoint by role — an agent drafts, submits and revises but never approves, rejects or publishes; an officer approves, rejects and publishes but never drafts or revises.

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

List endpoints are paginated through two query parameters. `limit` caps the number of items returned; it defaults to 10, has a minimum of 1 and a maximum of 100. `offset` is the number of items to skip and defaults to 0; it must not be negative. A `limit` outside 1 through 100, or a negative `offset`, is a malformed request and is rejected with `ERR_INVALID_REQUEST` (400).

Unless a specific endpoint says otherwise, every list is sorted by `created_at` in ascending order.

List responses carry `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope, where `total_count` is the size of the full filtered result set before the window is applied and `has_more` indicates whether any items remain beyond the current window.

### 2.4. Common Resource Properties and the Logical Clock

Every resource in the system carries a server-minted `id`, formatted as a UUID with no type prefix, and a `created_at` timestamp expressed as an ISO 8601 UTC string with three fractional digits.

Most resources additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation, and `version`, an integer that starts at 1 and increments by one on every mutation of that resource. `Business`, `Location`, `Listing`, `Contact`, `ResponseTemplate`, `Campaign`, `ReviewRequest`, `Review`, `ReviewResponse`, `Escalation`, `SurveyResponse` and `Widget` all carry both. Two entities are append-only snapshots and are never modified after creation: a `Competitor` row and an `Alert` row carry only `id` and `created_at` — they have no `updated_at` and no `version` field at all.

Crucially, a mutation of a *derived* field counts as a mutation. When the server recomputes a location's scores, counters or posture as a downstream consequence of some other action, that location's `updated_at` is refreshed and its `version` is incremented, exactly as if the operator had edited it directly. This is what makes the concurrency control in §2.8 bite.

Time in this system is a **logical clock**, never the host's wall clock. At server startup the clock reads exactly `2026-05-01T00:00:00Z`, and it holds that value until a `PlatformAdmin` moves it by supplying a `to_iso8601` instant to the clock-setting capability, which answers with the new `current_utc`. Every timestamp the server stamps — `created_at`, `updated_at`, `sent_at`, `last_synced_at`, `published_at`, `resolved_at`, `submitted_at`, `certified_at`, `expires_at` — and every window, decay, cooldown and expiry comparison in this document reads that logical clock. Moving the clock mutates nothing and fires no deferred work; it only changes what "now" means for the next request.

### 2.5. Location Posture: the Master Gate

Every `Location` carries a computed `posture` field whose value is one of `OPEN`, `RESTRICTED` or `FROZEN`. A newly created location starts at `OPEN`. Posture is never set directly by an operator; the server re-derives it immediately after every mutation that changes any of its four inputs — the location's `compliance_hold` flag, its `reputation_score_provisional`, its `open_escalation_count`, or its `listing_health_score`.

The derivation reads as follows. If the location's `compliance_hold` is true, the posture is `FROZEN` and nothing else is consulted. Otherwise the server arms up to three degradation predicates:

- **The score predicate.** It is armed only once the location has at least 3 non-flagged reviews — that is, once `review_count` is 3 or more. When armed, it fires if `reputation_score_provisional` is strictly below 60.00. The boundary is inclusive on the passing side: a score of exactly 60.00 does not degrade the location, while 59.99 does. Below three reviews the predicate is not armed at all, because a thin sample must never gate the business.
- **The escalation predicate.** Always armed. It fires when `open_escalation_count` is 3 or more.
- **The listing-health predicate.** Always armed. It fires when `listing_health_score` is strictly below 40.00.

If any armed predicate fires, the posture is `RESTRICTED`; if none fires, the posture is `OPEN`. Note the practical consequence for a brand-new location: it is born `OPEN` with a `listing_health_score` of 0.00, and the very first mutation that triggers a posture re-derivation will find that score below 40.00 and drive it to `RESTRICTED` until listings are attached and successfully synced.

Posture is a gate with two distinct strengths. `FROZEN` blocks **every** mutating operation on the location and on every entity beneath it — listings, campaigns, review requests, reviews, responses, escalations, surveys and the widget — and it also blocks the certification checkpoint of §3.8, which although it reads like a read is a mutation. A blocked operation is rejected with `ERR_LOCATION_FROZEN` (409). Exactly two mutations remain legal while frozen: placing or clearing the compliance hold itself, and a contact opting out. `RESTRICTED` is much narrower: it blocks only two operations, campaign activation and widget publication, both of which demand a posture of exactly `OPEN`; those two are rejected with `ERR_LOCATION_RESTRICTED` (409) when the posture is `RESTRICTED`, and with `ERR_LOCATION_FROZEN` when it is `FROZEN`. Every other child operation remains perfectly legal under `RESTRICTED`.

### 2.6. Recomputation Order and Cascade Discipline

The location's derived fields form a dependency chain, and the server evaluates them in a pinned order after any mutation that feeds them: **`listing_health_score` first, then `reputation_score_provisional` (which consumes it), then `posture` (which consumes both, plus the counters).** No fixed-point iteration is required or permitted. The counters `review_count`, `avg_rating`, `responded_review_count`, `sentiment_positive_count`, `sentiment_neutral_count`, `sentiment_negative_count` and `open_escalation_count` are refreshed before the scores that read them.

Cascades in this system run deep, and each link must complete before the next is evaluated. The two longest chains are worth stating up front, because implementers who stop at the first link will produce wrong counters:

- **The review-ingest chain.** Ingesting a review recomputes the location's counters and provisional score (link 1), which may drive the posture out of `OPEN` (link 2), which system-pauses every `RUNNING` campaign at that location (link 3), which suppresses every one of those campaigns' `QUEUED` requests and releases their credits.
- **The publish chain.** Publishing a reply flips the review's reply dimension to `RESPONDED` (link 1), which resolves every still-open escalation on that review (link 2), which decrements the location's `open_escalation_count`, recomputes `reputation_score_provisional` and re-derives `posture` (link 3) — potentially returning the location from `RESTRICTED` to `OPEN`.

Campaigns that the system paused are **never** auto-resumed when the posture recovers. A human must activate them again.

### 2.7. Scoring Precision and Rounding Discipline

All monetary and score values are represented in API responses as JSON numbers, and all of them are carried to exactly 2 decimal places using **round half up**. Intermediate products are kept exact; rounding is applied at the point each formula nominates, and nowhere else. Two rounding orders in this document are load-bearing and must not be transposed:

- The listing health score rounds **once, at the very end**, after the three weighted per-site contributions have been summed. The per-site base figures and their state factors are never rounded on the way in.
- Campaign billing rounds **per line, then sums**. Each individual message's `unit_cost` is rounded to 2 decimal places first, and only then are the rounded lines added together. Summing the raw products and rounding once at the end produces a different — and wrong — figure. Three SMS messages at the full rate, for example, are three separately-rounded lines of 0.08 each, totalling 0.24; they are not 0.23.

Integer-valued derived fields (`review_count`, `send_index`, `review_volume_delta`, the credit counters, the sentiment counters) are exact integers and are not rounded.

### 2.8. Optimistic Concurrency Control

Two write operations require the client to prove it is acting on a version of the parent it has actually observed. Both use a plain, non-optional integer field in the request body.

Creating a campaign under a location requires `expected_location_version`, carrying the client's last observed `version` of that `Location`. If it does not equal the location's current `version`, the create is rejected with `ERR_STALE_VERSION` (412). The reason is that both the campaign's send-window admissibility and its later activation gate are functions of the location's posture and of the other campaigns already attached to it; a create carrying a stale location version is acting on a view of the location that no longer holds. A successful create increments the location's `version` by one.

Creating a reply to a review requires `expected_review_version`, carrying the client's last observed `version` of that `Review`. If it does not equal the review's current `version`, the create is rejected with `ERR_STALE_VERSION` (412). A newly drafted reply legitimately supersedes the reply workflow on that review — it flips the review's reply dimension to `DRAFTED` — so a second create carrying the version the client observed before the first draft existed is acting on a stale review. A successful create increments the review's `version` by one.

No other endpoint in this specification takes a version field, and no other endpoint performs an OCC check.

### 2.9. Nested Path Resolution and Validation Precedence

Path identifiers are resolved strictly left to right, and the request is rejected at the **first** identifier that fails to resolve, with the 404 error belonging to that identifier's type: `ERR_BUSINESS_NOT_FOUND`, `ERR_LOCATION_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_CAMPAIGN_NOT_FOUND`, `ERR_REQUEST_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND`, `ERR_RESPONSE_NOT_FOUND`, `ERR_ESCALATION_NOT_FOUND`, `ERR_SURVEY_NOT_FOUND` or `ERR_WIDGET_NOT_FOUND`. Identifiers referenced in a request *body* are resolved after the path and must also belong to the same tenant: a `contact_id` must name a `Contact` of the same business (`ERR_CONTACT_NOT_FOUND`), a `template_id` must name a `ResponseTemplate` of the same business (`ERR_TEMPLATE_NOT_FOUND`), and a `review_request_id` supplied at ingest must name a `ReviewRequest` whose campaign belongs to the location being ingested into (`ERR_REQUEST_NOT_FOUND`).

When several checks could reject one request, the earliest in the following order wins, so that the client always sees the most fundamental reason for the rejection:

1. Authentication — headers present and role recognised (`ERR_UNAUTHENTICATED`).
2. Authorization — the role appears in the endpoint's authorized-role list (`ERR_UNAUTHORIZED`).
3. Tenant scoping — the `BusinessOwner` or `LocationManager` identity owns the target (`ERR_CROSS_TENANT_ACCESS`).
4. Path existence, left to right (the 404 family above).
5. Body-reference existence and tenancy (`ERR_CONTACT_NOT_FOUND`, `ERR_TEMPLATE_NOT_FOUND`, `ERR_REQUEST_NOT_FOUND`).
6. Request well-formedness — required fields present, types correct, enum members recognised, `rating` between 1 and 5 inclusive, `nps_score` between 0 and 10 inclusive, send-window strings well-formed with the close strictly after the open, `limit` within 1 to 100 and `offset` not negative (`ERR_INVALID_REQUEST`).
7. Optimistic concurrency — `expected_location_version` and `expected_review_version` (`ERR_STALE_VERSION`).
8. The `FROZEN` gate (`ERR_LOCATION_FROZEN`).
9. The `RESTRICTED` gate on activation and widget publication (`ERR_LOCATION_RESTRICTED`).
10. State-machine legality — the requested transition is declared for the entity's current state (`ERR_INVALID_STATE`).
11. Survey expiry (`ERR_SURVEY_EXPIRED`).
12. Contact consent (`ERR_CONTACT_OPTED_OUT`).
13. Segregation of duties (`ERR_SEGREGATION_OF_DUTIES`).
14. Template rating band (`ERR_TEMPLATE_RATING_MISMATCH`).
15. Publish requires a connected listing (`ERR_LISTING_NOT_CONNECTED`).
16. Escalation resolve requires a responded review (`ERR_REVIEW_NOT_RESPONDED`).
17. Listing uniqueness (`ERR_DUPLICATE_LISTING`).
18. Review uniqueness (`ERR_DUPLICATE_EXTERNAL_REVIEW`).
19. Widget uniqueness (`ERR_WIDGET_ALREADY_EXISTS`).
20. Send-window collision (`ERR_SEND_WINDOW_CONFLICT`).
21. Per-contact frequency cap (`ERR_FREQUENCY_CAP_ACTIVE`).
22. Credit availability (`ERR_INSUFFICIENT_CREDITS`).
23. Daily send cap (`ERR_SEND_CAP_EXCEEDED`).

Note in particular that compliance beats commerce: a frozen location, an opted-out contact and a segregation-of-duties breach all surface *before* the fiscal checks, so an operator can never mask a compliance failure behind a credit failure.

### 2.10. The Alert Feed

`Alert` rows are the location's notification stream. They are appended by the system, never by an operator, and they are immutable once written. Each carries the `location_id` it belongs to, an `alert_type`, a `severity`, a human-readable `message`, and a `payload_ref_id` naming the `id` of the entity that triggered it. That reference is for identity only and is never read back as a decision input.

Five alert types exist, and each has a fixed severity that never varies:

- `NEGATIVE_REVIEW` — severity `WARNING`.
- `LISTING_SYNC_FAILED` — severity `WARNING`.
- `NPS_DETRACTOR` — severity `WARNING`.
- `POSTURE_CHANGED` — severity `CRITICAL`.
- `SEND_CAP_REACHED` — severity `INFO`.

Every posture change — degradation, recovery, freeze and unfreeze alike — appends a `POSTURE_CHANGED` alert whose `payload_ref_id` is the location's own `id`. The alert feed can be filtered by `alert_type`.

## 3. Business Logic & Workflows

### 3.1. Onboarding a Tenant: Businesses, Locations, Contacts and Templates

Everything begins with a **`Business`**, registered by a `PlatformAdmin` with a `name`. Two commercial settings are optional at registration. The `plan_tier` is one of `BASIC`, `PRO` or `ENTERPRISE` and defaults to `BASIC`. The `default_frequency_cap_days` is the per-contact outreach cooldown, in whole days, that every campaign of this tenant will honour; it must be at least 1 and defaults to 30. A business also exposes a `location_count`, which the server maintains as the number of locations beneath it and which begins at 0.

Beneath a business sit its **`Location`** rows, each created with a display `name` and, more importantly, with the canonical **NAP record** — the three fields `nap_name`, `nap_address` and `nap_phone` that constitute this location's ground truth for Name, Address and Phone. That record is the source of truth pushed outward to the external sites; the sites' own copies never overwrite it. Each location knows its parent through `business_id`, and creating one raises the parent's `location_count` by one. A fresh location is `OPEN`, with a `listing_health_score` of 0.00, a `reputation_score_provisional` of 0.00, a `reputation_score_certified` of 0.00, a null `certified_at`, an `avg_rating` of 0.00, an `nps_score` of 0.00, and every counter at zero. Locations can be listed under their business and filtered by `posture`.

Replacing the canonical NAP record is a significant act and is expressed by supplying a fresh `nap_name`, `nap_address` and `nap_phone` together. It increments the location's `version` by one, it kicks every `CONNECTED` listing of that location back to `PENDING_SYNC` (leaving the sites' published copies untouched, which is precisely what makes their match counts drop), and it then re-runs the recomputation chain of §2.6 — listing health, then provisional score, then posture.

The marketing audience is the tenant's **`Contact`** list, hung off the business by `business_id`. A contact carries a `full_name`, an optional `email`, an optional `phone` in E.164 form, and two consent booleans: `sms_consent`, which defaults to false, and `email_consent`, which defaults to true. Two further fields are system-owned and cannot be supplied at creation: `opted_out`, a global kill switch that starts false, and the outreach history pair `last_requested_at` (the instant at which the most recent request for this contact was enqueued, null until the first one) and `request_count` (how many have ever been enqueued, starting at 0). A contact can opt out at any time, from any role including the public one, and doing so sets `opted_out` to true; this is one of only two mutations that remain legal while a location is `FROZEN`. Contacts can be listed and filtered by `opted_out`.

Finally, a business curates its **`ResponseTemplate`** library — the canned replies a `ResponseAgent` will reach for. A template carries a `name`, the `body` text that will be seeded into any reply built from it, and a rating band defined by `min_rating` (at least 1, at most 5) and `max_rating` (at least `min_rating`, at most 5). The last field, `requires_approval`, is a conditional feature flag that defaults to true and that governs whether replies built from this template must pass through a human approval hop at all; §3.4 spells out exactly what happens when it is false.

### 3.2. Listings, the NAP Record and Listing Health

Each location connects to the outside world through **`Listing`** rows, one per external site. A listing is attached to its parent by `location_id` and names its `site` — `GOOGLE`, `YELP` or `FACEBOOK` — together with the `external_listing_id` the site itself uses. At most one listing may exist per location and site combination; a second attempt is rejected with `ERR_DUPLICATE_LISTING`. Creation also captures what is *currently* published out there, in `listed_nap_name`, `listed_nap_address` and `listed_nap_phone`, which may well disagree with the location's canonical record. A new listing enters `PENDING_SYNC` with `sync_failure_count` at 0 and `last_synced_at` null, and attaching it immediately re-runs the recomputation chain of §2.6.

The listing's derived `nap_match_count` is the number of the three NAP parts — name, address, phone — where the published value equals the canonical value under case-sensitive exact string comparison. It therefore ranges from 0 to 3.

Pushing the canonical record out to a site is the **sync** operation. A `BusinessOwner` (or `PlatformAdmin`) invokes it and reports the connector's `outcome`, which is either `SUCCESS` or `FAILURE`.

On `SUCCESS` — legal from `PENDING_SYNC` and from `SYNC_FAILED` — the listing lands in `CONNECTED`. The three published fields are overwritten with the canonical ones, so `nap_match_count` becomes 3 by construction; `last_synced_at` is stamped with the current logical instant; and `sync_failure_count` is reset to 0. On `FAILURE`, the published fields are left exactly as they were and `sync_failure_count` climbs by one, an alert of type `LISTING_SYNC_FAILED` is appended, and the listing's `sync_state` moves according to how many consecutive failures have now accumulated. A first failure takes the listing from `PENDING_SYNC` to `SYNC_FAILED`. Further failures keep it cycling `SYNC_FAILED → SYNC_FAILED` for as long as the increment leaves the counter below the ceiling of three consecutive failures. The failure that pushes the counter *to* three — that is, the one applied when the counter already stands at 2 — drives the listing to `DISCONNECTED`. `DISCONNECTED` is terminal: any further sync attempt on it is rejected with `ERR_INVALID_STATE`. Note that a `SYNC_FAILED` listing already sitting at three failures likewise has no legal sync transition left. Every one of these outcomes, success or failure, re-runs the recomputation chain. Sync is blocked entirely while the location is `FROZEN`.

There is one further, system-driven transition: when the canonical NAP record is replaced (§3.1), every `CONNECTED` listing of that location falls back to `PENDING_SYNC`, and because its published copies are deliberately not touched, its `nap_match_count` drops by one for each part that actually changed.

**The `listing_health_score`.** This is the location's 0-to-100 measure of how faithfully the three sites represent it, and it is deliberately unforgiving about *absence*. All three sites are always weighted, so a site with no listing row at all contributes a per-site score of zero for its weight. Google carries a weight of 0.5, Yelp 0.3, and Facebook 0.2.

For a site that does have a listing, the per-site score is built in three steps. First, a **base**: the listing's `nap_match_count` divided by three, expressed as a percentage — so all three parts matching gives 100, two parts gives the exact value of two-thirds of a hundred, one part gives one-third of a hundred, and none gives 0. This base is kept exact and is never rounded here. Second, a **state factor** multiplying that base, fixed by the listing's `sync_state`: `CONNECTED` multiplies by 1.0, `PENDING_SYNC` by 0.6, `SYNC_FAILED` by 0.3, and `DISCONNECTED` by 0.0. Third, a **staleness penalty** subtracted from the product. Staleness is measured in whole days between `last_synced_at` and the current logical instant, taking the floor of the elapsed time in days; a listing that has never had a successful sync — `last_synced_at` still null — is treated as maximally stale at 365 days. The first week is free: only days beyond a grace period of 7 count. The penalty is 2 points for each such day beyond the grace period, and it is capped at 30 points. The per-site score is then clamped into the range 0.0 to 100.0.

The location's `listing_health_score` is the sum of the three weighted per-site scores — Google's at 0.5, Yelp's at 0.3, Facebook's at 0.2 — rounded half up to 2 decimal places exactly once, at the end. Because a location with no listings at all scores 0.00, and because 0.00 is below the 40.00 listing-health floor of §2.5, an unlisted location is `RESTRICTED` as soon as anything causes its posture to be re-derived.

### 3.3. Review Ingest, Sentiment, and the Moderation Dimension

Reviews arrive through a `PlatformAdmin`-only site-connector ingest. Each **`Review`** is attached to its `location_id` and carries the `site` it came from (`GOOGLE`, `YELP` or `FACEBOOK`), the site-native `external_review_id`, the `author_name` as published, the `text` of the review body, an integer `rating` between 1 and 5 inclusive, and `posted_at`, the instant it went live on the external site. A review may optionally carry a `review_request_id` linking it back to the outreach message that produced it; organic reviews that no campaign produced leave that null. No two reviews may share the same location, site and `external_review_id` — a repeat is rejected with `ERR_DUPLICATE_EXTERNAL_REVIEW`.

A `Review` is unusual in that it lives in **two independent state dimensions at once**, and an action in one leaves the other completely untouched.

The first dimension is `moderation_state`, which tracks authenticity. Every review lands at `UNVERIFIED`. A `LocationManager` may confirm it, taking it `UNVERIFIED → VERIFIED`, or repudiate it, taking it `UNVERIFIED → FLAGGED` or `VERIFIED → FLAGGED`. A false flag can be undone: `FLAGGED → VERIFIED` reinstates the review. Flagging accepts an optional free-text `reason`. Both verification and flagging are barred while the location is `FROZEN`, and either one applied to a review already in the destination state is an `ERR_INVALID_STATE`.

The second dimension is `response_state`, the reply workflow, whose values are `NONE`, `DRAFTED`, `AWAITING_APPROVAL`, `APPROVED` and `RESPONDED`. It starts at `NONE` and is driven entirely by the reply machine of §3.4.

**Sentiment.** At ingest, and exactly once — it is never recomputed afterwards, no matter what happens to the review — the server assigns the review's `sentiment` from its `rating`. A rating of 4 or above is `POSITIVE`. A rating of 2 or below is `NEGATIVE`. That leaves a rating of exactly 3 as the only `NEUTRAL` value.

A `NEGATIVE` sentiment at ingest is not a passive label; it fires two things. An `Escalation` is appended against the review with `reason` `NEGATIVE_SENTIMENT` and `state` `OPEN`, which raises the location's `open_escalation_count` by one. And an alert of type `NEGATIVE_REVIEW` is appended, pointing at the review.

**What ingest does to the location.** Only reviews whose `moderation_state` is `UNVERIFIED` or `VERIFIED` count toward the location's aggregates; `FLAGGED` reviews are excluded from all of them. Over that non-flagged set, the server maintains `review_count` (its size), `avg_rating` (the mean `rating`, rounded half up to 2 decimal places, and 0.00 when the set is empty), the three sentiment tallies `sentiment_positive_count`, `sentiment_neutral_count` and `sentiment_negative_count`, and `responded_review_count` (how many of them have reached a `response_state` of `RESPONDED`). Ingesting a review refreshes all of these, then the provisional reputation score, then the posture — and if the posture leaves `OPEN`, the campaign cascade of §2.6 and §3.6 follows.

Moderation moves the same machinery. Flagging a review removes it from every counter and from both score input sets, and — as a compensating action for the auto-escalation raised at ingest — every escalation of that review still sitting in `OPEN` or `ACKNOWLEDGED` is `CANCELLED`, with `open_escalation_count` reduced by one for each. Verifying an `UNVERIFIED` review changes no counter (the review was already inside the non-flagged set), but the scores and posture are still re-derived. Reinstating a `FLAGGED` review to `VERIFIED` puts it back into every counter, and if its `sentiment` is `NEGATIVE`, a *fresh* `OPEN` escalation with `reason` `NEGATIVE_SENTIMENT` is raised against it and `open_escalation_count` climbs again.

Reviews can be listed and filtered by `location_id`, `review_request_id`, `moderation_state` and `sentiment`.

### 3.4. The Reply Workflow: Draft, Approve, Publish

A **`ReviewResponse`** is the brand's public reply. A `ResponseAgent` drafts one against a review by supplying the reply `body`, an optional `template_id`, and the concurrency token `expected_review_version` described in §2.8. The response is attached to the review by `review_id`, is created in `state` `DRAFT`, and records the acting `X-User-ID` in `drafted_by_user_id` — the key on which segregation of duties will later turn. Its `approved_by_user_id`, `rejection_reason` and `published_at` all begin null, and its `revision_count` begins at 0. Creating it flips the review's reply dimension `NONE → DRAFTED` and increments the review's `version` by one. A review may only be replied to once: a second draft attempt against a review whose reply dimension is anything other than `NONE` is an `ERR_INVALID_STATE`. A review whose `moderation_state` is `FLAGGED` cannot be replied to at all.

When a `template_id` is supplied, the template's rating band must contain the review's rating: the template's `min_rating` must be at or below the review's `rating` and its `max_rating` at or above it. A band that does not contain the rating is rejected with `ERR_TEMPLATE_RATING_MISMATCH` (422). A reply with a null `template_id` is a free-form response that no template backs, and no band check applies to it.

**Submitting** the draft is where the conditional feature flag bites, and the two branches diverge sharply.

- If the response has no template at all, *or* if its backing template has `requires_approval` set to true, the submit takes the response `DRAFT → PENDING_APPROVAL` and the review's reply dimension `DRAFTED → AWAITING_APPROVAL`. A human must now look at it.
- If, and only if, the response has a non-null `template_id` whose template has `requires_approval` set to false, the submit collapses the approval hop entirely: the response goes straight `DRAFT → APPROVED` and the review's reply dimension goes straight `DRAFTED → APPROVED`. Because no human approved it, `approved_by_user_id` is explicitly left null, and the segregation-of-duties check is bypassed altogether.

Submitting anything that is not in `DRAFT` is an `ERR_INVALID_STATE`.

**Approval and rejection** belong to the `ComplianceOfficer` (and to `PlatformAdmin`), and both act only on a response in `PENDING_APPROVAL`. Both are guarded by segregation of duties: the acting `X-User-ID` must differ from the response's `drafted_by_user_id`, and a self-approval or self-rejection is rejected with `ERR_SEGREGATION_OF_DUTIES` (403) regardless of how privileged the actor's role is. Approving takes the response `PENDING_APPROVAL → APPROVED`, stamps `approved_by_user_id` with the approver's `X-User-ID`, and moves the review's reply dimension to `APPROVED`. Rejecting takes the response `PENDING_APPROVAL → REJECTED` and stores the supplied `rejection_reason`; notably, the review's reply dimension does *not* move — it stays at `AWAITING_APPROVAL` until the response is actually revised.

**Revision** closes the cycle. The drafting agent takes a `REJECTED` response back to `DRAFT` by supplying a replacement `body`; this raises `revision_count` by one and returns the review's reply dimension to `DRAFTED`. The loop `DRAFT → PENDING_APPROVAL → REJECTED → DRAFT` may be walked as many times as needed.

**Publication** is the terminal act, performed by a `ComplianceOfficer` on an `APPROVED` response, and it demands a live channel: a listing must exist for the review's own location and site combination, and that listing's `sync_state` must be `CONNECTED`. A missing listing, or one in any other sync state, is rejected with `ERR_LISTING_NOT_CONNECTED` (409). On success the response reaches `PUBLISHED` — a terminal state — and `published_at` is stamped. That is link one of the publish chain: the review's reply dimension advances `APPROVED → RESPONDED`; link two resolves every escalation of that review still sitting in `OPEN` or `ACKNOWLEDGED`; and link three drops the location's `open_escalation_count` by one for each escalation so resolved, refreshes `responded_review_count`, recomputes `reputation_score_provisional`, and re-derives `posture` — which is how a location earns its way back from `RESTRICTED` to `OPEN` once all three degradation predicates clear.

Every one of these five reply transitions — submit, approve, reject, revise, publish — is barred while the location is `FROZEN`. Responses can be listed and filtered by `review_id`, `template_id` and `state`.

### 3.5. Escalations

An **`Escalation`** is the operational to-do raised against a negative review. It is never created by an operator; it appears only as the ingest-time consequence of a `NEGATIVE` sentiment or as the reinstatement-time consequence of un-flagging a negative review, in both cases with a `reason` of `NEGATIVE_SENTIMENT` and a `state` of `OPEN`, bound to its `review_id`. Escalations of a review can be listed.

A `LocationManager` may **acknowledge** an `OPEN` escalation, taking it `OPEN → ACKNOWLEDGED` and stamping `acknowledged_by_user_id` with the acting `X-User-ID`. Acknowledgement is a signal of human attention, not of closure: an `ACKNOWLEDGED` escalation still counts toward the location's `open_escalation_count`, which is therefore left completely unchanged by this transition.

**Resolving** an escalation — from `OPEN` or from `ACKNOWLEDGED` — closes it for good, stamping `resolved_at`, dropping the location's `open_escalation_count` by one and re-deriving the posture. When a human resolves it manually, the underlying review must already have been replied to: its reply dimension must read `RESPONDED`, and if it does not, the request is rejected with `ERR_REVIEW_NOT_RESPONDED` (409). The system cascade from publication faces no such barrier, because that cascade is itself what set the review to `RESPONDED` in the first place.

The other terminal outcome is **cancellation**, and it is never requested directly. Flagging a review cancels every escalation of that review in `OPEN` or in `ACKNOWLEDGED`, taking each to `CANCELLED` and decrementing `open_escalation_count` for each, then re-deriving posture. This is the compensating action that restores the counter to the value it had before the ingest that raised the escalation. `RESOLVED` and `CANCELLED` are both terminal; a resolve attempt against either is an `ERR_INVALID_STATE`. Acknowledging and resolving are barred while the location is `FROZEN`.

### 3.6. Campaigns: Scheduling, Credits, Sending and Attribution

A **`Campaign`** is a review-request programme attached to a location by `location_id`. Creating one is the OCC-guarded write of §2.8: it demands `expected_location_version` alongside the campaign's `name`, its `channel` (`SMS` or `EMAIL`, and every request the campaign later produces inherits it), the `message_body` sent to contacts, the daily send window defined by `send_window_start` and `send_window_end`, the `daily_send_cap` (at least 1), and `credits_allocated` (at least 0, the total message credits granted to the campaign). The send-window fields are 24-hour UTC clock strings in `HH:MM` form; the close must be strictly later in the day than the open, in minutes since midnight, and a malformed or inverted window is an `ERR_INVALID_REQUEST`. A new campaign is born in `DRAFT` with all three credit ledger fields — `credits_reserved`, `credits_consumed` and `credits_released` — at 0, `sent_count` at 0, `billing_cost` at 0.00, and `activated_at` null. The create increments the location's `version` by one. Campaigns can be listed under a location and filtered by `status`.

**Scheduling** takes the campaign `DRAFT → SCHEDULED`, and it is the moment the send-window collision check runs. Consider any *other* campaign at the same location, on the same `channel`, whose `status` is `SCHEDULED`, `RUNNING` or `PAUSED`. Convert both windows to minutes since midnight and expand the candidate's window symmetrically by a channel buffer of a quarter of an hour — 15 minutes — on each side. The candidate collides with that other campaign when the candidate's buffered open is at or before the other's close **and** the candidate's buffered close is at or after the other's open. These are closed intervals: touching exactly at the buffer edge *is* a collision. Any collision rejects the schedule with `ERR_SEND_WINDOW_CONFLICT` (409). Scheduling a campaign that is not in `DRAFT` is an `ERR_INVALID_STATE`.

**Activation** takes the campaign `SCHEDULED → RUNNING` or, after a pause, `PAUSED → RUNNING`. It is one of the two operations that demand a posture of exactly `OPEN`: a `RESTRICTED` location rejects it with `ERR_LOCATION_RESTRICTED` and a `FROZEN` one with `ERR_LOCATION_FROZEN`. The first activation of a campaign's life stamps `activated_at` with the current logical instant, and this is the anchor of the BROAD attribution window described below; **a later re-activation never moves it.**

**Pausing** comes in two flavours, and the difference is the single most consequential asymmetry in this section. A *manual* pause by a `LocationManager` takes the campaign `RUNNING → PAUSED` and leaves the queue intact: every `QUEUED` request stays queued and its reserved credit stays reserved. A *system* pause — the one triggered whenever the location's posture leaves `OPEN`, whether by degrading to `RESTRICTED` or by being frozen — also takes the campaign `RUNNING → PAUSED`, but it additionally **empties the queue**: every `QUEUED` request of that campaign is moved to `SUPPRESSED`, and for each one, `credits_reserved` drops by one while `credits_released` rises by one. That is the third link of the ingest cascade, and it is why a single incoming one-star review can reach four entities deep: review, location, campaign, request.

**Completion** takes the campaign `RUNNING → COMPLETED` or `PAUSED → COMPLETED`, and, like the system pause, it suppresses every remaining `QUEUED` request with the same credit release per request. `COMPLETED` is terminal.

**Enqueuing a request.** A **`ReviewRequest`** is created against the campaign by naming a `contact_id`; the request records its `campaign_id`, copies the campaign's `channel` at enqueue time, and lands in `QUEUED` with a null `send_index`, a null `unit_cost`, a null `sent_at` and a null `converted_review_id`. Three gates guard the enqueue, and they run in that order.

First, **consent**, which beats every commercial rule beneath it. The contact must not have `opted_out` set. If the campaign's channel is `SMS`, the contact must have `sms_consent` true and a non-null `phone`. If the channel is `EMAIL`, the contact must have `email_consent` true and a non-null `email`. Any failure is `ERR_CONTACT_OPTED_OUT` (403).

Second, the **per-contact frequency cap**. Let the anchor be the contact's `last_requested_at`. If it is null, the contact has never been contacted and the enqueue is always allowed. Otherwise the cooldown occupies the half-open interval that begins at the anchor and runs for the tenant's `default_frequency_cap_days`. An enqueue is rejected with `ERR_FREQUENCY_CAP_ACTIVE` (409) whenever the current logical instant is at or after the anchor and strictly before the anchor plus the cap; an enqueue at *exactly* the anchor plus the cap is allowed, because the interval's end is exclusive.

Third, **credit availability**. The campaign's `credits_allocated`, less its `credits_reserved`, less its `credits_consumed`, must leave at least 1 credit free. If it does not, the enqueue is rejected with `ERR_INSUFFICIENT_CREDITS` (402).

On success, one credit is reserved (`credits_reserved` rises by one), the contact's `last_requested_at` is stamped with the current logical instant and its `request_count` rises by one.

**Cancelling** a `QUEUED` request takes it to `SUPPRESSED` and is the compensating action for the enqueue: `credits_reserved` falls by one and `credits_released` rises by one, so that the conserved quantity — allocated less reserved less consumed — returns to exactly its pre-enqueue value. The contact's `last_requested_at` is deliberately **not** rolled back: the frequency-cap window survives cancellation, so a cancelled request still burns the contact's cooldown. Cancelling anything not in `QUEUED` is an `ERR_INVALID_STATE`.

**Sending a batch.** A `LocationManager` drains up to `batch_size` `QUEUED` requests to `SENT`, taking them in `created_at` ascending order. The campaign must be `RUNNING` (anything else is `ERR_INVALID_STATE`), the location must not be `FROZEN`, and the campaign must have at least one credit left when measured as `credits_allocated` less `credits_consumed`. The daily cap is then checked **for the batch as a whole**: the number of this campaign's requests already moved to `SENT` on the current UTC calendar day, plus the number this batch would send, must not exceed `daily_send_cap`. If it would, the entire batch is rejected with `ERR_SEND_CAP_EXCEEDED` (422) and nothing is partially sent. When a batch consumes the very last unit of the daily cap exactly, an alert of type `SEND_CAP_REACHED` is appended against the campaign.

Each request that goes out receives a `send_index` — a 1-based counter that runs across the campaign's whole lifetime, assigned as the maximum index already handed out in this campaign plus one, distributed across the batch in `created_at` ascending order — a `sent_at` stamp at the current logical instant, and a `unit_cost`. Per sent request, `credits_reserved` falls by one and `credits_consumed` rises by one; the campaign's `sent_count`, which is the number of its requests that have reached `SENT`, `DELIVERED`, `CLICKED`, `CONVERTED` or `FAILED`, is refreshed. The contact is not touched — its cooldown anchor was already stamped at enqueue. The batch operation answers with the number of requests it sent, the number of requests `remaining_queued` behind them, the campaign's new `billing_cost`, and the `campaign_status`.

**Billing.** The cost of a single message is the channel's base rate multiplied by a volume discount driven by that message's `send_index`, rounded half up to 2 decimal places. The base rate is 7.5 tenths of a cent per SMS — 0.075 — and 1.2 tenths of a cent per email — 0.012. The discount is a full 1.00 for the first 100 messages of the campaign's lifetime, drops to 0.90 for messages with a `send_index` from 101 through 500 inclusive, and drops again to 0.80 for every message beyond the 500th. The campaign's `billing_cost` is then the **sum of those already-rounded per-message costs** across every billable request — every request whose `status` is `SENT`, `DELIVERED`, `CLICKED`, `CONVERTED` or `FAILED`, taken in `created_at` ascending order. `QUEUED` and `SUPPRESSED` requests are not billable and contribute nothing. As §2.7 warns, rounding each line before summing is mandatory and produces a different number from summing first.

**Delivery outcomes.** The delivery connector reports back through a `PlatformAdmin`-only callback carrying an `event_type`. `DELIVERED` advances a `SENT` request to `DELIVERED`. `CLICKED` advances a `DELIVERED` request to `CLICKED`. `FAILED` takes a `SENT` request to `FAILED` — and the credit stays consumed, because a failed delivery is still billable. `CONVERTED`, `FAILED` and `SUPPRESSED` are the three terminal states of a request. Requests can be listed and filtered by `campaign_id`, `contact_id` and `status`.

**Attribution.** When a review is ingested carrying a `review_request_id`, the named request converts — from `SENT`, from `DELIVERED` or from `CLICKED` — to `CONVERTED`, and the new review's `id` is stamped into the request's `converted_review_id` (an identity record only, never a decision input). Conversion happens only if the review's `posted_at` falls inside the attribution window that opens at the request's `sent_at` and runs for 14 days, with the opening instant included and the closing instant excluded.

Campaign performance is reported through two deliberately different conversion rates, both over the same denominator: the count of that campaign's **billable** requests, meaning those whose `status` is `SENT`, `DELIVERED`, `CLICKED`, `CONVERTED` or `FAILED`. When that denominator is zero, both rates are 0.00.

- The **STRICT** rate, surfaced as `conversion_rate_strict`, is the number the platform bills marketing performance on. Its numerator counts reviews that are explicitly linked to one of this campaign's billable requests, whose `moderation_state` is `VERIFIED`, and whose `posted_at` falls inside that specific request's own 14-day window opening at its `sent_at` (start included, end excluded).
- The **BROAD** rate, surfaced as `conversion_rate_broad`, is the halo number shown to the customer. It ignores the request link entirely and ignores verification: its numerator counts every review at the campaign's location whose `moderation_state` is `UNVERIFIED` or `VERIFIED` and whose `posted_at` falls inside a single 14-day window opening at the campaign's own `activated_at` (start included, end excluded).

Each numerator is divided by the shared denominator, multiplied by 100, rounded half up to 2 decimal places, and then capped at 100.00. The same data therefore yields two different percentages. The metrics view also reports `sent_count`, `billing_cost`, and `credits_available` — the campaign's allocated credits less those reserved and less those consumed.

### 3.7. Surveys and NPS, Competitors, and the Website Widget

**Surveys.** A **`SurveyResponse`** is issued to a contact at a location by naming a `contact_id`; the row records its `location_id`, lands in `PENDING`, and is stamped with an `expires_at` set to a fortnight — 14 days — after its `created_at`. Its `nps_score`, `nps_category`, `comment` and `submitted_at` are all null while it is `PENDING`.

Submission is a **public** act: the recipient follows a link and answers, so `Anonymous` may both read the survey and submit it. The submission carries an integer `nps_score` between 0 and 10 inclusive and an optional free-text `comment`, moves the row to `SUBMITTED`, and stamps `submitted_at`. Timing is strict: the submission must happen strictly before `expires_at`. A submission at *exactly* `expires_at`, or after it, is already too late and is rejected with `ERR_SURVEY_EXPIRED` (409). Submitting a survey that is already `SUBMITTED` is an `ERR_INVALID_STATE`.

The submitted score is bucketed into `nps_category`: a score of 9 or above is a `PROMOTER`, a score of 6 or below is a `DETRACTOR`, and the scores 7 and 8 in between are `PASSIVE`. A `DETRACTOR` submission also appends an alert of type `NPS_DETRACTOR` pointing at the survey.

The location's `nps_score` — a different field on a different entity, carrying the standard Net Promoter shape — is then recomputed over that location's `SUBMITTED` surveys only; `PENDING` rows are excluded, and an empty set yields 0.00. Take the count of promoters divided by the number of submitted surveys, multiplied by 100; take the count of detractors divided by the same number, multiplied by 100; subtract the second percentage from the first; and round that difference half up to 2 decimal places. The subtraction happens before the single rounding. Surveys can be listed and filtered by `location_id`, `contact_id` and `status`.

**Competitors.** A **`Competitor`** row is an immutable benchmarking snapshot recorded against a location. It carries the competitor's `name`, the `site` the snapshot came from (`GOOGLE`, `YELP` or `FACEBOOK`), its `avg_rating` on that site (at least 1.00 and at most 5.00), and its `review_count` on that site (not negative). Because it is a snapshot, it has no `updated_at` and no `version`, as §2.4 notes.

**The widget.** A **`Widget`** is the review feed a location embeds on its own website, and a location may have **at most one** — a second creation attempt is rejected with `ERR_WIDGET_ALREADY_EXISTS` (409). It is created in `DRAFT` with a server-minted `embed_token` (an opaque identity string that is never a decision input) and a null `published_at`. Two optional settings shape the public feed: `min_rating`, the lowest review rating the feed will display, which must be between 1 and 5 inclusive and defaults to 4; and `max_reviews`, the maximum number of reviews the feed will display, which must be between 1 and 50 inclusive and defaults to 10. Publishing takes the widget `DRAFT → PUBLISHED` and stamps `published_at`; it is the second of the two operations that demand a posture of exactly `OPEN`, so a `RESTRICTED` location rejects it with `ERR_LOCATION_RESTRICTED`. And when a compliance hold lands on the location, any `PUBLISHED` widget is reverted to `DRAFT` with its `published_at` cleared back to null.

**The dashboard.** One read pulls the whole location picture together, computing the competitor benchmark on the fly and persisting nothing. It reports the location's `posture`, `review_count`, `avg_rating`, the three sentiment tallies `sentiment_positive_count`, `sentiment_neutral_count` and `sentiment_negative_count`, both reputation scores `reputation_score_provisional` and `reputation_score_certified`, the `listing_health_score`, the `nps_score`, the `open_escalation_count`, the `responded_review_count`, and three benchmark figures.

Those three are derived from every competitor row of the location, across all sites. When the location has no competitor rows at all, `competitor_avg_rating` is 0.00, `rating_delta` is simply the location's own `avg_rating` rounded half up to 2 decimal places, and `review_volume_delta` is simply the location's own `review_count`. Otherwise, `competitor_avg_rating` is the mean of the competitors' `avg_rating` values, rounded half up to 2 decimal places; `rating_delta` is the location's `avg_rating` minus that competitor mean, rounded half up to 2 decimal places; and `review_volume_delta` is an integer — the location's `review_count` minus the competitors' mean `review_count` with that mean rounded *down* to a whole number.

### 3.8. Reputation Scoring and the Certification Checkpoint

The reputation score is the number everything else in this system hangs on, and it exists in **two variants that share one shape but read different data**. Both are on a 0-to-100 scale and both are assembled from three weighted components, summed and then rounded half up to 2 decimal places exactly once at the end:

- A **rating component** worth up to 60 points: the variant's average star rating divided by 5, multiplied by 60. An empty review set yields an average of 0 and therefore contributes 0 points.
- A **response component** worth up to 25 points: the variant's response rate — the fraction of the variant's reviews whose reply dimension reads `RESPONDED` — multiplied by 25. An empty review set yields a rate of 0 and therefore contributes 0 points.
- A **listing component** worth up to 15 points: the location's `listing_health_score` divided by 100, multiplied by 15. Both variants read the same, single `listing_health_score`.

Reviews whose `moderation_state` is `FLAGGED` are excluded from **both** variants. Beyond that, the variants part ways.

**The PROVISIONAL variant** is written to `reputation_score_provisional`, and it is the **only** score the posture derivation of §2.5 ever reads. Its review set is every review at the location whose `moderation_state` is `UNVERIFIED` or `VERIFIED`. Its average rating is the plain, unweighted mean of those reviews' `rating` values — no recency weighting whatsoever — and 0 when the set is empty. Its response rate is the count of those reviews whose reply dimension reads `RESPONDED`, divided by the size of that set, and 0 when the set is empty. It is refreshed after **every** review, response and listing mutation: after an ingest, a verify, a flag, a reply publication, a listing sync, a NAP replacement, and an escalation resolve.

**The CERTIFIED variant** is written to `reputation_score_certified`, and it is refreshed **only** by the audit checkpoint, never by ordinary traffic. It differs from the provisional variant in two ways. Its review set is narrower: only reviews whose `moderation_state` is exactly `VERIFIED` count, so unverified reviews are dropped entirely. And each surviving review carries a **recency weight** that decays with age. A review's age is the whole number of days between its `posted_at` and the current logical instant, taking the floor of the elapsed days. Its weight starts at 1 and loses 0.02 for every completed block of 30 days of age — the number of completed 30-day blocks being the age in days divided by 30 and rounded down — but the weight never falls below a floor of 0.5, however old the review is. The certified average rating is then the sum, over the certified review set, of each review's weight multiplied by its `rating`, divided by the sum of those same weights; it is 0 when the set is empty. The certified response rate, by contrast, carries **no** weighting: it is the plain count of certified-set reviews whose reply dimension reads `RESPONDED` divided by the size of that set, and 0 when the set is empty.

Because the two variants read different sets and weight them differently, identical data yields two different numbers whenever the sets diverge or any review is older than 30 days.

The **certification checkpoint** is the audit action, available to a `BusinessOwner` or a `PlatformAdmin`. It recomputes the CERTIFIED variant, writes it to `reputation_score_certified`, and stamps `certified_at` with the current logical instant. It deliberately does **not** touch `reputation_score_provisional` and does **not** re-derive the posture. It is nonetheless a mutation, and it is therefore barred while the location is `FROZEN`.

**Compliance holds.** A `PlatformAdmin` places or clears a hold by supplying the boolean `on_hold`. Setting it true takes the location from `OPEN` or from `RESTRICTED` to `FROZEN`, sets `compliance_hold` to true, system-pauses every `RUNNING` campaign at that location, reverts a `PUBLISHED` widget to `DRAFT` with a null `published_at`, appends a `POSTURE_CHANGED` alert, and increments the location's `version`. Setting it false clears `compliance_hold`, appends a `POSTURE_CHANGED` alert, increments `version`, and lets the posture derivation run again on the now-unheld location: it lands at `OPEN` if none of the three degradation predicates fires, and at `RESTRICTED` if any of them does. Campaigns paused by the freeze are not resurrected by the thaw; a human must activate them again.

## 4. Endpoint Definitions

Operations that bring a brand-new resource into existence — registering a business, creating a location, a contact, a template, a listing, a competitor, a widget, a campaign, a review request, an ingested review, a drafted response, or a survey — answer with `201 Created`. Every other operation, including state transitions, reads, batch sends, compliance holds and the certification checkpoint, answers with `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/reputation/businesses` | Register a tenant business | PlatformAdmin |
| GET | `/reputation/businesses/{id}` | Read a business | PlatformAdmin, BusinessOwner |
| POST | `/reputation/businesses/{id}/locations` | Create a location with its canonical NAP record | PlatformAdmin, BusinessOwner |
| GET | `/reputation/businesses/{id}/locations` | List the locations of a business | PlatformAdmin, BusinessOwner |
| POST | `/reputation/businesses/{id}/contacts` | Create a marketing contact | PlatformAdmin, BusinessOwner, LocationManager |
| GET | `/reputation/businesses/{id}/contacts` | List the contacts of a business | PlatformAdmin, BusinessOwner, LocationManager |
| POST | `/reputation/businesses/{id}/templates` | Create a response template | PlatformAdmin, BusinessOwner |
| GET | `/reputation/businesses/{id}/templates` | List the response templates of a business | PlatformAdmin, BusinessOwner, ResponseAgent |
| GET | `/reputation/locations/{id}` | Read a location including its posture and scores | PlatformAdmin, BusinessOwner, LocationManager, ResponseAgent, ComplianceOfficer |
| PUT | `/reputation/locations/{id}/nap` | Replace the location's canonical NAP record | PlatformAdmin, BusinessOwner |
| POST | `/reputation/locations/{id}/compliance-hold` | Place or clear a compliance hold | PlatformAdmin |
| POST | `/reputation/locations/{id}/certify` | Audit checkpoint: refresh the certified score | PlatformAdmin, BusinessOwner |
| GET | `/reputation/locations/{id}/dashboard` | Sentiment, rating, NPS, listing health and competitor benchmark | PlatformAdmin, BusinessOwner, LocationManager |
| GET | `/reputation/locations/{id}/alerts` | Alert feed for a location | PlatformAdmin, BusinessOwner, LocationManager |
| POST | `/reputation/locations/{id}/listings` | Attach an external site listing | PlatformAdmin, BusinessOwner |
| GET | `/reputation/locations/{id}/listings` | List the listings of a location | PlatformAdmin, BusinessOwner, LocationManager |
| POST | `/reputation/listings/{id}/sync` | Push the canonical NAP and record the connector outcome | PlatformAdmin, BusinessOwner |
| POST | `/reputation/locations/{id}/competitors` | Record an immutable competitor snapshot | PlatformAdmin, BusinessOwner, LocationManager |
| GET | `/reputation/locations/{id}/competitors` | List competitor snapshots | PlatformAdmin, BusinessOwner, LocationManager |
| POST | `/reputation/locations/{id}/widget` | Create the location's website review widget | PlatformAdmin, BusinessOwner, LocationManager |
| GET | `/reputation/locations/{id}/widget` | Read the location's widget | PlatformAdmin, BusinessOwner, LocationManager |
| POST | `/reputation/widgets/{id}/publish` | Publish the widget | PlatformAdmin, BusinessOwner, LocationManager |
| POST | `/reputation/contacts/{id}/opt-out` | Global opt-out for a contact | PlatformAdmin, BusinessOwner, LocationManager, Anonymous |
| POST | `/reputation/locations/{id}/campaigns` | Create a review-request campaign | PlatformAdmin, BusinessOwner, LocationManager |
| GET | `/reputation/locations/{id}/campaigns` | List the campaigns of a location | PlatformAdmin, BusinessOwner, LocationManager |
| GET | `/reputation/campaigns/{id}` | Read a campaign including its credit ledger | PlatformAdmin, BusinessOwner, LocationManager |
| POST | `/reputation/campaigns/{id}/schedule` | Schedule a campaign; runs the send-window collision check | PlatformAdmin, BusinessOwner, LocationManager |
| POST | `/reputation/campaigns/{id}/activate` | Activate a campaign | PlatformAdmin, BusinessOwner, LocationManager |
| POST | `/reputation/campaigns/{id}/pause` | Pause a running campaign | PlatformAdmin, BusinessOwner, LocationManager |
| POST | `/reputation/campaigns/{id}/complete` | Complete a campaign and suppress its queue | PlatformAdmin, BusinessOwner, LocationManager |
| POST | `/reputation/campaigns/{id}/requests` | Enqueue one review request for a contact | PlatformAdmin, BusinessOwner, LocationManager |
| POST | `/reputation/campaigns/{id}/send-batch` | Send a batch of queued requests | PlatformAdmin, BusinessOwner, LocationManager |
| GET | `/reputation/campaigns/{id}/metrics` | Campaign performance, billing and remaining credits | PlatformAdmin, BusinessOwner, LocationManager |
| GET | `/reputation/review-requests` | Filtered list of review requests | PlatformAdmin, BusinessOwner, LocationManager |
| GET | `/reputation/review-requests/{id}` | Read one review request | PlatformAdmin, BusinessOwner, LocationManager |
| POST | `/reputation/review-requests/{id}/events` | Delivery-connector callback | PlatformAdmin |
| POST | `/reputation/review-requests/{id}/cancel` | Cancel a queued request and release its credit | PlatformAdmin, BusinessOwner, LocationManager |
| POST | `/reputation/locations/{id}/reviews` | Site-connector ingest of one aggregated review | PlatformAdmin |
| GET | `/reputation/reviews` | Filtered review list | PlatformAdmin, BusinessOwner, LocationManager, ResponseAgent, ComplianceOfficer |
| GET | `/reputation/reviews/{id}` | Read one review with both state dimensions | PlatformAdmin, BusinessOwner, LocationManager, ResponseAgent, ComplianceOfficer |
| POST | `/reputation/reviews/{id}/verify` | Move moderation to VERIFIED | PlatformAdmin, LocationManager |
| POST | `/reputation/reviews/{id}/flag` | Move moderation to FLAGGED | PlatformAdmin, LocationManager |
| GET | `/reputation/reviews/{id}/escalations` | Escalations of a review | PlatformAdmin, BusinessOwner, LocationManager, ComplianceOfficer |
| POST | `/reputation/reviews/{id}/responses` | Draft a reply to a review | PlatformAdmin, ResponseAgent |
| GET | `/reputation/review-responses` | Filtered response list | PlatformAdmin, BusinessOwner, LocationManager, ResponseAgent, ComplianceOfficer |
| GET | `/reputation/review-responses/{id}` | Read one review response | PlatformAdmin, BusinessOwner, LocationManager, ResponseAgent, ComplianceOfficer |
| POST | `/reputation/review-responses/{id}/submit` | Submit a drafted reply for approval | PlatformAdmin, ResponseAgent |
| POST | `/reputation/review-responses/{id}/approve` | Approve a pending reply | PlatformAdmin, ComplianceOfficer |
| POST | `/reputation/review-responses/{id}/reject` | Reject a pending reply | PlatformAdmin, ComplianceOfficer |
| POST | `/reputation/review-responses/{id}/revise` | Revise a rejected reply | PlatformAdmin, ResponseAgent |
| POST | `/reputation/review-responses/{id}/publish` | Publish an approved reply | PlatformAdmin, ComplianceOfficer |
| POST | `/reputation/escalations/{id}/acknowledge` | Acknowledge an open escalation | PlatformAdmin, LocationManager |
| POST | `/reputation/escalations/{id}/resolve` | Resolve an escalation | PlatformAdmin, LocationManager |
| POST | `/reputation/locations/{id}/surveys` | Issue an NPS survey to a contact | PlatformAdmin, BusinessOwner, LocationManager |
| GET | `/reputation/surveys` | Filtered survey list | PlatformAdmin, BusinessOwner, LocationManager |
| GET | `/reputation/surveys/{id}` | Read one survey | PlatformAdmin, BusinessOwner, LocationManager, Anonymous |
| POST | `/reputation/surveys/{id}/submit` | Public NPS submission | Anonymous, PlatformAdmin |
| POST | `/reputation/_clock/set_current_utc` | Set the server's logical clock | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_CROSS_TENANT_ACCESS` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_CONTACT_OPTED_OUT` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_BUSINESS_NOT_FOUND` | 404 Not Found |
| `ERR_LOCATION_NOT_FOUND` | 404 Not Found |
| `ERR_LISTING_NOT_FOUND` | 404 Not Found |
| `ERR_CONTACT_NOT_FOUND` | 404 Not Found |
| `ERR_TEMPLATE_NOT_FOUND` | 404 Not Found |
| `ERR_CAMPAIGN_NOT_FOUND` | 404 Not Found |
| `ERR_REQUEST_NOT_FOUND` | 404 Not Found |
| `ERR_REVIEW_NOT_FOUND` | 404 Not Found |
| `ERR_RESPONSE_NOT_FOUND` | 404 Not Found |
| `ERR_ESCALATION_NOT_FOUND` | 404 Not Found |
| `ERR_SURVEY_NOT_FOUND` | 404 Not Found |
| `ERR_WIDGET_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_LOCATION_FROZEN` | 409 Conflict |
| `ERR_LOCATION_RESTRICTED` | 409 Conflict |
| `ERR_SURVEY_EXPIRED` | 409 Conflict |
| `ERR_LISTING_NOT_CONNECTED` | 409 Conflict |
| `ERR_REVIEW_NOT_RESPONDED` | 409 Conflict |
| `ERR_TEMPLATE_RATING_MISMATCH` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_LISTING` | 409 Conflict |
| `ERR_DUPLICATE_EXTERNAL_REVIEW` | 409 Conflict |
| `ERR_WIDGET_ALREADY_EXISTS` | 409 Conflict |
| `ERR_SEND_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_FREQUENCY_CAP_ACTIVE` | 409 Conflict |
| `ERR_INSUFFICIENT_CREDITS` | 402 Payment Required |
| `ERR_SEND_CAP_EXCEEDED` | 422 Unprocessable Entity |
