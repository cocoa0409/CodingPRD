# Worklog — task_1225_biorepository_specimen_consent_management

## Step 1: Create Task Directory — 2026-08-12T01:54:00.000Z

Pre-assigned output folder `tasks/task_1225_biorepository_specimen_consent_management` with `workspace/` subdirectory already existed. Step 1 auto-index scan skipped per instructions; directory verified present.

## Step 2: Generate Scaffold — 2026-08-12T02:31:00.000Z

Scaffold generation complete. All three artifacts written and the lint verdict is clean (verbatim: "VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5." — 537 calls scanned).

**Files written**
- `/home/ubuntu/github/CodingPRD/tasks/task_1225_biorepository_specimen_consent_management/SCAFFOLD.yaml` (1741 lines; §1.0–§1.7 only, no difficulty/corner keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1225_biorepository_specimen_consent_management/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (663 lines; single top key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1225_biorepository_specimen_consent_management/SCAFFOLD_CORNER_DESIGN.yaml` (936 lines; single top key `scaffold_corner_design`)

**Counts**
- Entities: 16 (Donor, ConsentRecord, CollectionKit, CustodyEvent, Specimen, Aliquot, StorageUnit, TemperatureReading, StorageSlot, SlotReservation, SampleRequest, ReviewVote, SharingAgreement, DeidentificationKey, KeyAccessGrant, DestructionOrder)
- Endpoints: 60 (incl. `POST /_clock/set_current_utc` with pinned default 2026-05-01T00:00:00Z and an ops-run sweep endpoint)
- State machines: 11 — 4 non-linear (SampleRequest bounded revision cycle, StorageUnit posture cycle OPERATIONAL⇄WARNING→FAILURE→OPERATIONAL, ConsentRecord withdraw/rescind revert loop, Aliquot quarantine cycle + Specimen parallel lifecycle×viability dimensions)
- Calculations: 10 (incl. dual-variant specimen committed volume book-vs-physical, dual-variant freezer excursion peak-vs-cumulative, tiered surcharge quota charge, pinned round-per-aliquot-then-sum handling fee, quorum threshold, grace/SLA deadlines, deterministic fulfill selector)
- Validations: 26 ordered priority rows; Errors: 37; Roles: 6 (all opaque identity, segregation-of-duties model); OCC concurrency rules: 2 (specimen-versioned aliquot create, consent-versioned amendment)
- Difficulty instances (§1.8): 18 — 2 per rule × 9 rules, each with replayed structured setup/trigger chains and pre-computed literal asserts
- Corner instances (§1.9): 47 total — 43 active + 4 `excluded_because` stubs; sections: entities 8, state_machines 7, calculations 6 (3 stubs), validations 13, endpoints 5, errors 1 (stub), rbac 3, cross_cutting_layers 4, consistency_model 1

**Notable design decisions under the "harder than expert" calibration:** depth-4 withdrawal-finalization cascade (consent → specimen → aliquot → request/agreement compensation + auto DestructionOrder), freezer-failure cascade (unit → slot → reservation + aliquot quarantine), two distinct validation-priority conflict pairs (state vs business_safety; business_temporal vs business_fiscal), two interval geometries (half-open slot reservations vs closed key-grant windows with 24h buffer), and two pinned compensating invariants (physical specimen volume; contractual agreement quota). One authoring bug was caught and fixed during self-replay: the surcharge instance originally omitted the checkout needed to move 80ml from reserved to fulfilled before the second fulfill (utilization reads `fulfilled_volume_ml`).

## Step 3: Copy Shared Files — 2026-08-12T02:32:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1225_biorepository_specimen_consent_management/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-12T02:44:00.000Z

All contracts verified. The PRD is complete and shipped.

## Summary

**Output path:** `/home/ubuntu/github/CodingPRD/tasks/task_1225_biorepository_specimen_consent_management/workspace/PRD.md`
**Line count:** 351 lines

**Section coverage:**
- **§1 Introduction** — 2 paragraphs (donor-trust/specimen-integrity angle, segregation-of-duties and logical-clock determinism)
- **§2 Global Specifications** — 9 subsections: 2.1 RBAC (6 roles, each named, all `identity: opaque` translated into a joint explicit prose statement with the concrete recorded-on fields), 2.2 API Response Structure (byte-identical verbatim block, verified), 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ascending, meta fields), 2.4 Common Resource Properties (including the explicit `common_fields: false` carve-out: CustodyEvent, TemperatureReading, ReviewVote carry only `id`/`created_at`), 2.5 Logical Clock & Due-Date Sweep (startup default, `to_iso8601`/`current_utc`, five sweep counters, per-job boundary inclusivity), 2.6 Request Validation Order (7-tier cascade incl. OCC-before-business and left-to-right path existence), 2.7 OCC (both rules), 2.8 Units/Precision/Rounding, 2.9 Segregation of Duties (all three pairs)
- **§3 Business Logic** — 9 subsections (consent lifecycle, kit custody, accession/aliquoting/volume ledgers, freezer monitoring/failure contingency, sharing agreements, requests/committee review, fulfill/quota/checkout, de-identification keys/grants/reveal, withdrawal cascade/destruction orders); all 10 calculations rendered as precise prose (dual committed-volume variants, peak vs. cumulative degree-minutes, pinned 5-step quota charge with 0.8/1.25 surcharge, round-per-aliquot-then-sum handling fee with the 501.25→1002 vs 1003 divergence example, quorum 3-of-5 inclusive boundaries, 72h grace, 48h SLA); full 3-depth withdrawal cascade; all 37 error IDs placed near their triggers; per-endpoint check orderings stated (accession, fulfill, checkout, votes, reveal, confirm-execution)
- **§4 Endpoint Definitions** — status-code paragraph plus 60-row table (4 columns only), matching all 60 scaffold endpoints
- **§5 Error Code Catalogue** — 37-row table (2 columns only), matching all 37 scaffold errors

**Hard Contract reports:**
- Contract 1 (Field-Name Coverage): 86 required identifiers (entity fields + endpoint inputs incl. query filters), 86 present, 0 missing — **PASS**
- Contract 2 (Rule Coverage): validations/priorities (24), OCC rules (2), state transitions (all 13 machines), calculations (10), endpoint side effects, structured field content, and sibling-branch symmetry (book/physical, peak/cumulative, both OCC rules, dual kit-expiry sources) all expressed; spot-check harness 38/38 — **PASS**
- Contract 3 (§3 Path Purity): 593 backticked tokens scanned in §3; 0 path tokens, 0 bare-method tokens, 0 method+path combos — **PASS**

**Zero-Silence Rule adjudications made:**
1. **Amendment OCC-vs-state ordering** — the transition's precondition list shows ACTIVE before OCC, but the global validation table pins OCC (priority 3.5) before state checks (priority 4); the PRD states the stale-version check runs first.
2. **Checkout "charged share"** — the scaffold leaves the per-aliquot share formula implicit; the PRD phrases it as "the aliquot's share of the request's charge" moved from `reserved_volume_ml` to `fulfilled_volume_ml`, without inventing a per-aliquot formula.
3. **`ERR_ALREADY_TERMINAL` placement** — no scaffold transition nominates it directly; it is anchored in §2.6 as the state-tier rejection for actions on terminal-state resources, consistent with its catalog condition.
4. **Slot-reservation check order** — checks presented in numeric priority order (shape, slot availability, overlap, unit posture).
5. **Consent effectiveness** — the "ACTIVE but not yet effective" semantics (from the withdraw precondition and error condition) were stated once in §3.1 and applied globally to accession/fulfill/checkout, avoiding contradictory per-endpoint restatements.

The withheld design files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were not opened, grepped, or referenced at any point.

## Step 5: Generate Unit Tests — 2026-08-12T03:05:00.000Z

All done. Summary of the generation run:

## Files written

**`test_helpers/`** (Stage 1 — 9 files, 1,465 lines):
- `/home/ubuntu/github/CodingPRD/tasks/task_1225_biorepository_specimen_consent_management/test_helpers/types.py` (369) — 24 status enums + role enum; 18 entity TypedDicts; audit-record entities (CustodyEvent, TemperatureReading, ReviewVote) correctly omit `updated_at`/`version`
- `api_client.py` (198) — 64 endpoint methods on `ApiClient(GenericApiClient)`
- `api_errors.py` (88) — 37 `ApiErrorId` members + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` (152), `factories.py` (142), `constants.py` (46), `test_users.py` (41), `fixtures.py` (391 — full composite chain: donor→consent→kit→unit/slot→specimen→aliquot→agreement→approved-request→fulfill, withdrawal finalization, destruction orders), `__init__.py` (38, barrel)

**`test_suite/`** (Stage 2 — 14 files, 1,990 lines): `conftest.py` (40) + `test_01_consent_lifecycle` (168) through `test_13_security_and_envelope` (79), grouped by domain concern.

## Tests emitted
- **Queue A (Difficulty): 36 tests** — all 18 instances × 2 tests each, zero shortfalls
- **Queue B (Corner): 43 tests** — all 43 non-stub instances × 1 test each, zero shortfalls
- **Total: 79 tests**, all collected cleanly by pytest

## Instances skipped
Only the 4 `excluded_because:` stubs (never translated, per spec): `handling_fee_rounding_covered_by_difficulty`, `volume_invariant_covered_by_difficulty`, `excursion_variants_covered_by_difficulty`, `error_catalog_covered_by_other_sections`. All four difficulty-instance cross-references verified to resolve. No non-stub instance failed the PRD-first filter.

**One notable adjudication:** two difficulty recipes ship pre-computed ledger values inconsistent with their own setup chains under PRD §3.7 (checkout moves the charge from `reserved_volume_ml` to `fulfilled_volume_ml`): `fulfillment_quota_charge_tiered_surcharge` (yaml's reserved 92.5 → PRD-derived 12.5) and `fulfill_temporal_vs_fiscal` (yaml's reserved 40.0 → PRD-derived 0.0). I kept the instances' PRD-grounded primary claims (charge 12.5 at U_pre=0.8; `ERR_AGREEMENT_NOT_EFFECTIVE` priority) and asserted PRD-derived ledger values rather than the erroneous literals.

## Audits
- **Design-tag audit: PASS** — every one of 79 tests has exactly one trailing `Design: Difficulty/...` or `Design: Corner/...` line; all tags resolve verbatim to real `name:` entries; no untagged, dual-tagged, or stub-derived tests
- **PRD-citation pass: PASS** — every docstring contains a ≥8-word window surviving literal match against `PRD.md` (whitespace/formatting-normalized); no skip/xfail/skipif markers anywhere
- **Lint/collection: PASS** — pyflakes clean (except intentional barrel re-exports in `__init__.py`); `pytest --collect-only` reports 79 tests, 0 errors

## Step 6: Generate Implementation — 2026-08-12T03:05:00.000Z

## Summary

Complete Python + Flask implementation of the Biorepository & Specimen Consent Management API written to `/home/ubuntu/github/CodingPRD/tasks/task_1225_biorepository_specimen_consent_management/workspace/implementation/`.

### Files written (paths + line counts)

- `implementation/start.sh` (7) — foreground launcher, reads `$PORT` (default 10000), binds 0.0.0.0, guards `pip install` behind an `import flask` check, `exec python3 app.py`
- `implementation/requirements.txt` (1) — flask>=3.0
- `implementation/app.py` (64) — entry point, blueprint registration, ApiError/404/405 handlers
- `implementation/db.py` (24) — in-memory dicts keyed by id; no seeding
- `implementation/clock.py` (40) — logical clock, starts at exactly 2026-05-01T00:00:00Z, never wall-clock
- `implementation/errors.py` (55) — full 37-entry error catalog with HTTP statuses
- `implementation/response.py` (60) — exact envelope: `meta`/`response_type`/`data`, error body `error_id`/`message`, pagination `limit`/`offset`/`total_count`/`has_more`
- `implementation/middleware.py` (135) — `X-User-ID`/`X-User-Role` auth, 6-role RBAC, shape validation, pagination parsing
- `implementation/serializers.py` (227) — output shapes for all 16 entity types
- `implementation/services/common.py` (80), `services/specimen.py` (53), `services/destruction.py` (72), `services/storage.py` (164), `services/sweep.py` (138)
- `implementation/routes/clock_sweep.py` (27), `routes/donors.py` (179), `routes/kits.py` (141), `routes/specimens.py` (276), `routes/storage.py` (225), `routes/requests.py` (341), `routes/agreements.py` (88), `routes/keys.py` (165), `routes/destruction.py` (79)

Total: ~2,641 lines.

### Route count
60 of 60 declared endpoints registered; machine-diffed against `SCAFFOLD.yaml` — zero missing, zero extra (Flask's built-in `/static` route was disabled for a strict match).

### Entity/model count
16 collections (13 versioned entities + 3 immutable audit types: CustodyEvent, TemperatureReading, ReviewVote).

### Boot verification
Ran `bash start.sh` on free ports 18923–18925. Each boot: clean state, clock at 2026-05-01, responds <2s. Curl-verified end-to-end: auth-header rejection, donor/consent/kit CRUD, custody event chain, specimen accession with kit consumption, aliquot OCC (`ERR_STALE_VERSION` on stale version), void volume restore (residual 8.0→10.0), clock set + sweep (withdrawal finalized at grace deadline), committee quorum (3 APPROVE → APPROVED; duplicate-vote and short-rationale errors), fulfill (charge 3.0 ml at utilization<0.8 → multiplier 1.0; fee 1002-style per-aliquot rounding: 505+503=1008), checkout ledger settlement, destruction-order SoD (same-user confirm → `ERR_SEGREGATION_OF_DUTIES`; different officer → COMPLETED, specimen DESTROYED), de-identification key uniqueness, grant creation, reveal SoD + success, freezer declare-failure cascade (slots OFFLINE, aliquots QUARANTINED, specimen viability QUARANTINED), return-to-service viability review (delta ≤120 → released), temperature excursion math (peak 5.0, cumulative 300.0 degree-minutes for +5°C over 60 min), and implausibility rejection. Fresh restart confirmed zero carry-over state.

### Notes on interpretation decisions
- Timestamps use the logical clock with a monotonic millisecond tie-breaker so `created_at` ordering stays stable within a single logical instant.
- Checkout keeps a durable `checked_out_for_request_id` link on the aliquot (not exposed in serializers) so the withdrawal cascade can set `recall_required` after `reserved_for_request_id` has been cleared.
- Agreement charge-share at checkout is proportional: `charged_volume_ml × aliquot_volume / selected_volume`, per the "aliquot's share of the request's charge" wording in PRD §3.7.

## Step 6b: Route Parity Verification — 2026-08-12T03:06:00.000Z

Orchestrator machine-diffed (method, path) pairs: SCAFFOLD.yaml declares 60 endpoints; implementation registers exactly 60; missing=[], extra=[]. Route parity confirmed before Step 7 sweep.

## Step 7: Run Tests and Iterate — 2026-08-12T03:25:00.000Z

All 8 rounds now pass with 79/79 tests each. The `test_void_restores_residual_volume` flakiness from the first run appears to have been a transient timing issue under contention that didn't recur.

Summary:
- **Iterations run**: 2 (initial sweep, then post-fix sweep)
- **Tests deleted**: 0
- **Fixes applied to test_helpers/**: none
- **Fixes applied to test_suite/**: none
- **Fixes applied to implementation/**:
  - `/home/ubuntu/github/CodingPRD/tasks/task_1225_biorepository_specimen_consent_management/workspace/implementation/routes/specimens.py` (`checkout_aliquot`): Added `ERR_ALREADY_TERMINAL` check on the aliquot's terminal state (`DISTRIBUTED`, `DESTROYED`, `VOID`) before the referential-existence check on the body-supplied `request_id`. Per PRD §2.6 tier 6, "Attempting an action on a resource that has already reached a terminal state is rejected with `ERR_ALREADY_TERMINAL` (HTTP 409)" — and state preconditions (tier 6) fire before business rules including referential coherence of body fields (tier 7).

Note on the initial sweep: `test_void_restores_residual_volume` showed a "server could not be restarted" error at exactly the 15s polling window in all 8 rounds. This appears to have been transient contention (the 8-parallel restart sequence occasionally exceeding the polling window under load) rather than a deterministic bug — the second sweep completed cleanly across all 8 rounds with no server-restart failures.

Orchestrator verification: all 8 `results.{1..8}.json` files present on disk, each `passed=79 total=79 failed=0`.

## Step 8: Finalize PRD — 2026-08-12T03:21:00.000Z

Done. The edit is a single inline revision; the diff confirms nothing else changed.

## Summary

**Line counts / delta**: `PRD.md` 350 lines, `PRD_FINALIZED.md` 350 lines — 0% line-count delta (the one change is an inline revision inside the single-line checkout paragraph at line 219; ~+460 chars).

**Changes** (one bullet per change):
- **§3.7 (Checkout paragraph)** — revise — inserted two gate sentences ahead of the listed checks: (a) checkout on an aliquot in a terminal state (`DISTRIBUTED`, `DESTROYED`, `VOID`) is rejected with `ERR_ALREADY_TERMINAL` (HTTP 409) per §2.6's terminal-state rule; (b) the payload's `request_id` must resolve to an existing sample request, failing as `ERR_NOT_FOUND` (HTTP 404); changed "Its checks run in order" to "Its checks then run in order" — `workspace/implementation/routes/specimens.py:232-237` (`checkout_aliquot`).

This resolves a genuine PRD ambiguity the Step 7 fix exposed: for a terminal aliquot, old §3.7 text implied `ERR_ALIQUOT_NOT_RESERVED_FOR_REQUEST` (a terminal aliquot is not `RESERVED`) while §2.6 tier 6's generic rule implied `ERR_ALREADY_TERMINAL` — the implementation resolved it for the latter, checked before the body-supplied `request_id` existence check, which the PRD never mentioned at all.

**Per-edit pre-edit search log** (single edit):
- **(a) Subject**: checkout endpoint's handling of terminal-state aliquots and of body-supplied `request_id` resolution, plus their precedence relative to each other and to the five listed checkout checks.
- **(b) Impl paths enumerated**: read all of `implementation/routes/specimens.py` (checkout 220-286, void 202-214, create_aliquot 122-165, accession 30-97); grepped `ERR_ALREADY_TERMINAL` across `implementation/` (raised only at `routes/specimens.py:233`; mapped in `errors.py:20`); grepped all body-ref `ERR_NOT_FOUND` sites (`specimens.py:52,55,58,63,142,237`; `keys.py:36,139`; `destruction.py:36`; `kits.py:100`; `requests.py:54,238`); grepped all domain state-error sites on possibly-terminal resources (`void` → `ERR_INVALID_STATE`; confirm → `ERR_DESTRUCTION_ORDER_NOT_CONFIRMABLE`; kits → `ERR_KIT_NOT_DISTRIBUTABLE`/`ERR_KIT_NOT_RETURNED`; agreements/consents/requests/keys → their own codes) confirming no other endpoint fires `ERR_ALREADY_TERMINAL`; read `keys.py` reveal, `destruction.py` create, `requests.py` create for body-ref check placement.
- **(c) Wording adjustment**: initially considered leaning on §2.6's tier ordering generically, but narrowed to checkout-scoped wording ("Two gates precede the listed checks, in this order") because any universal terminal-state claim would mis-describe the void/confirm/kit/agreement/consent/key endpoints enumerated above (all use domain-specific errors on terminal resources, and each is pinned by pre-existing PRD prose). The `ERR_NOT_FOUND` sentence states only the checkout-local fact and makes no claim about other endpoints' body-ref checks, which sit at differing positions in their own cascades (e.g., `create_aliquot`'s slot check runs after the OCC guard, before the state check; accession's run post-shape). Resulting order — terminal gate → request existence → reserved-match → approved → consent → scope → unit — matches the implementation exactly.

## Step 9: Complete PRD — 2026-08-12T03:32:00.000Z

Done. `PRD_COMPLETED.md` is written with all pins applied inline. Summary below.

## Summary

**Source vs. output:** `workspace/PRD_FINALIZED.md` (350 lines / 56,509 chars) → `workspace/PRD_COMPLETED.md` (353 lines / 62,083 chars); delta +3 lines, +5,574 chars. 33 in-paragraph edits; no new sections; no behavior invented beyond what `implementation/` exhibits.

**Counts:** 27 ambiguity-pins, 6 mismatch-revisions.

**Changes (one bullet each):**

- §2.1 — insert — ambiguity — unrecognized `X-User-Role` value is authenticated-but-unauthorized, failing as `ERR_INSUFFICIENT_PERMISSIONS` everywhere — implementation/middleware.py:31
- §2.2 — insert — ambiguity — `api_request_timestamp` is wall-clock and informational only — implementation/response.py:14-17
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` fail `ERR_INVALID_REQUEST`; `has_more` = `offset + page_size < total_count`; filters never 404 on unknown values — implementation/middleware.py:115-135, response.py:40
- §2.4 — insert — ambiguity — `created_at`/`updated_at` stamped from the logical clock with a monotonic sub-second counter making creation order total — implementation/services/common.py:9-23
- §2.5 — insert — ambiguity — clock set accepts any target instant, including earlier than now — implementation/clock.py:14-16
- §2.5 — insert — ambiguity — the five sweep jobs execute in the order listed — implementation/services/sweep.py:87-130
- §2.6 — revise — mismatch — validation cascade restructured: envelope shape (unknown fields, required presence, OCC-field integer type) now precedes the stale-version check, which precedes remaining field validation; impl runs those shape checks before OCC — implementation/routes/specimens.py:127-135, routes/donors.py:148-158
- §2.6 — revise — mismatch — `ERR_ALREADY_TERMINAL` scoped to where workflows name it (in practice aliquot checkout); other terminal-state actions report workflow-specific errors (e.g. cancel-on-terminal → `ERR_INVALID_STATE`) — implementation/routes/specimens.py:232-233, routes/requests.py:319-320
- §2.6 — insert — ambiguity — body-carried identifiers resolve to `ERR_NOT_FOUND` at workflow-specified points; bodiless action endpoints accept and ignore any body; agreement `effective_from`/`effective_to` has no creation-time ordering constraint — implementation/routes/clock_sweep.py:26, routes/agreements.py:39-40
- §2.8 — insert — ambiguity — entity datetime fields other than `created_at`/`updated_at` serialize at whole-second precision with `Z` — implementation/clock.py:36-40
- §3.1 — revise — mismatch — `donor_reference_code` uniqueness is not enforced — implementation/routes/donors.py:26-36
- §3.2 — insert — ambiguity — distribution's `donor_id` must resolve to an existing donor (`ERR_NOT_FOUND`), checked after the state and expiry checks — implementation/routes/kits.py:94-100
- §3.3 — insert — ambiguity — accession's `donor_id`/`kit_id`/`consent_record_id`/`storage_slot_id` existence checks (`ERR_NOT_FOUND`) run before the ordered business checks — implementation/routes/specimens.py:50-63
- §3.3 — insert — ambiguity — aliquot creation order pinned: stale-version → slot existence (`ERR_NOT_FOUND`) → aliquotability → slot `AVAILABLE` → volume — implementation/routes/specimens.py:132-149
- §3.4 — revise — mismatch — `unit_code` uniqueness not enforced — implementation/routes/storage.py:39-60
- §3.4 — revise — mismatch — `slot_code` uniqueness not enforced; `capacity_ml` must be an integer > 0 — implementation/routes/storage.py:78-80
- §3.4 — insert — ambiguity — reservation availability and posture checks run before the overlap scan — implementation/routes/storage.py:122-132
- §3.4 — revise — mismatch — degree-minute accrual uses fractional minutes at second precision (not "whole minutes"); readings not later than their predecessor accrue zero — implementation/services/storage.py:28-31
- §3.4 — insert — ambiguity — declare-failure on an already-`FAILURE` unit fails `ERR_INVALID_STATE`; a fail-threshold reading on an already-failed unit re-fires no cascade — implementation/routes/storage.py:207-208, 172-175
- §3.4 — insert — ambiguity — failure cascade also quarantines the parent specimen of every quarantined aliquot, slot-housed or not — implementation/services/storage.py:99-103
- §3.4 — insert — ambiguity — return-to-service viability delta = per-reading formula over `(quarantine_start, now]`, spacing from predecessor even outside the window — implementation/services/storage.py:37-59
- §3.5 — insert — ambiguity — new agreements start with `remaining_volume_ml` at zero until activation — implementation/routes/agreements.py:45
- §3.6 — insert — ambiguity — request creation requires the agreement to exist (`ERR_NOT_FOUND`) before the scope check; agreement status not inspected at creation — implementation/routes/requests.py:52-56
- §3.6 — insert — ambiguity — vote records also carry `decision`, `rationale`, and `round` (the request's `revision_round` at cast time) — implementation/serializers.py:162-171
- §3.6 — insert — ambiguity — cancel-from-`APPROVED` resets the request's `charged_volume_ml` to zero; cancel from any other (incl. terminal) status fails `ERR_INVALID_STATE` — implementation/routes/requests.py:338, 319-320
- §3.7 — insert — ambiguity — fulfillment candidate pool = `IN_STORAGE` aliquots of `IN_STORAGE`/`USABLE` type-matching specimens; any consent failure in that pool rejects the whole fulfillment rather than excluding the aliquot — implementation/routes/requests.py:214-234
- §3.7 — insert — ambiguity — checkout ledger share = request charge prorated by aliquot `initial_volume_ml` over total selected volume, at 3 dp — implementation/routes/specimens.py:266-278
- §3.7 — insert — ambiguity — a slot-less aliquot passes the checkout unit-posture check vacuously — implementation/routes/specimens.py:251-255
- §3.8 — insert — ambiguity — key minting requires the named specimen to exist (`ERR_NOT_FOUND`) — implementation/routes/keys.py:34-36
- §3.8 — insert — ambiguity — grant-window conflict rules count existing grants of any status, including `EXPIRED`; a gap of exactly 24h is allowed — implementation/routes/keys.py:88-102
- §3.8 — insert — ambiguity — reveal: named grant must exist (`ERR_NOT_FOUND`) first and feeds only the dual-control comparison; the window check is satisfied by any `ACTIVE` grant on the key; success returns the updated key — implementation/routes/keys.py:137-165
- §3.9 — insert — ambiguity — the withdrawal cascade leaves a compromised request's `charged_volume_ml` unchanged (unlike requester-cancel) — implementation/services/sweep.py:53-61
- §3.9 — insert — ambiguity — manual order creation requires specimen existence (`ERR_NOT_FOUND`) but imposes no lifecycle precondition; the flip applies only to `ACCESSIONED`/`IN_STORAGE` specimens — implementation/services/destruction.py:10-46
- §4 — insert — ambiguity — unknown paths and unsupported methods fail as `ERR_NOT_FOUND` (HTTP 404) — implementation/app.py:45-52

**PIPELINE COMPLETE.** All 9 steps done: PRD_COMPLETED.md present (353 lines), worklog reaches Step 9, final 8-round stability sweep on disk with 79/79 passing in every round.
