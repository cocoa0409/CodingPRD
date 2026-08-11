# Worklog — task_1116_hazmat_transportation_compliance

## Step 1: Create task directory — 2026-08-10T17:48:32.226Z

Task directory pre-assigned by the caller: `tasks/task_1116_hazmat_transportation_compliance` with `workspace/` subdirectory already created. Auto-index scan skipped per instructions. Scenario: "generate task hard than expert level! 1116. Hazmat Transportation Compliance & Placarding (hazmat shipper compliance office): shipment classification & proper shipping name determination, packaging authorization & marking/labeling, placard selection & vehicle segregation rules, shipping paper & emergency response information, driver training & endorsement verification, security plan & route restriction, incident reporting timelines, carrier registration & fees".

## Step 2: Generate scaffold — 2026-08-10T18:38:00.000Z

Scaffold generation complete for task 1116 (Hazmat Transportation Compliance & Placarding), designed harder-than-expert per the difficulty parameter. All three files written and verified on disk:

**Files**
- `/home/ubuntu/github/CodingPRD/tasks/task_1116_hazmat_transportation_compliance/SCAFFOLD.yaml` — 97,103 bytes (§1.0–§1.7 only; no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1116_hazmat_transportation_compliance/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 109,949 bytes (single top key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1116_hazmat_transportation_compliance/SCAFFOLD_CORNER_DESIGN.yaml` — 96,693 bytes (single top key `scaffold_corner_design`)

**Counts**
- Entities: 14 (Carrier, SecurityPlan, HazmatMaterial, PackagingSpec, Driver, TrainingRecord, Vehicle, Shipment, ShippingPaper, VehicleLoad, LoadItem, Route, IncidentReport, RegistrationInvoice)
- Endpoints: 66 (incl. `POST /hazmat/_clock/set_current_utc` with pinned default 2026-05-01T00:00:00Z)
- State machines: 10 (cycles on Carrier, Shipment, ShippingPaper, VehicleLoad, SecurityPlan; branching on IncidentReport)
- Calculations: 12 (registration fee with provisional/final variants + tiered/late/discount/pre-fee-bracket ordering; incident penalty reported/confirmed variants; placard Table-1/Table-2 with 454.0 kg inclusive threshold and DANGEROUS substitution; per-line-then-sum handling fee; segregation pairing; 90-day anchored training extension; driver posture; security-plan selector; payment waterfall; safety rating; outstanding balance)
- Validations: 22 ordered priorities; Errors: 66; Roles: 3 (CarrierAdmin, ShipperComplianceOfficer, Regulator; segregation-of-duties on classify vs certify); OCC concurrency rules: 2 (shipment amend, carrier registration submit — both 412 ERR_STALE_VERSION)
- Difficulty-design instances: 20 (9 rule_ids × ≥2; combinatorial_formula and non_linear_state_machine carry 3 each; all money arithmetic in asserts pre-computed, e.g. provisional 27500 vs final 26250; renewal 47500; penalty 90000 → 209000; fee 788 vs rejected 787 reading)
- Corner-design instances: 45 total (38 active + 7 `excluded_because` stubs, all stub references verified to resolve to §1.8 instance names; zero name collisions across both files)

**Verification**: `scaffold_lint.py` verdict pasted verbatim — "VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5." (649 calls scanned: 20 §1.8 + 38 active §1.9 instances.) Two fix rounds were needed: quoting `${var}`/`$.data[N]` scalars in flow mappings, and renaming nested parent path placeholders to `{id}` plus adding 3 reverse-reachability GETs (`GET /hazmat/shipments`, `GET /hazmat/vehicle-loads/{id}/items`, `GET /hazmat/incident-reports/{incidentId}`) to clear 14 FK_REVERSE_UNREACHABLE violations.

## Step 3: Copy shared files — 2026-08-10T18:38:30.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1116_hazmat_transportation_compliance/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-10T18:56:00.000Z

(First attempt exited mid-plan without writing the file; re-spawned with an explicit must-write requirement.)

PRD.md is complete on disk at 341 lines with all three hard contracts passing.

## Summary

**File written:** `/home/ubuntu/github/CodingPRD/tasks/task_1116_hazmat_transportation_compliance/workspace/PRD.md` — 341 lines.

**Section list:**
- §1. Introduction (3 paragraphs: pain points, system scope, SoD/OCC framing)
- §2. Global Specifications — 2.1 RBAC (opaque identity translated for all three roles, SoD recording points named); 2.2 API Response Structure (emitted verbatim from `section-2.2-response-structure.md`); 2.3 Pagination (limit default 10 / min 1 / max 100, offset 0, created_at ASC, plus per-list filter parameters); 2.4 Logical Clock & sweeps (startup 2026-05-01T00:00:00Z, `to_iso8601`, three sweep effects); 2.5 Common Resource Properties (UUID ids, ISO 8601 with 3 fractional digits, version semantics, `TrainingRecord`/`LoadItem` as the no-`updated_at`/no-`version` exceptions); 2.6 OCC (both rules with exact fields, `ERR_STALE_VERSION`/412, no time-overlap framing); 2.7 Money/rounding (integer cents, per-component round-half-up); 2.8 Validation order (auth → role → path left-to-right → shape → FK → OCC → carrier gate → from-state → domain rules); 2.9 Uniqueness constraints.
- §3. Business Logic — 9 subsections (registration & fee schedule; payments/waterfall; catalogs & retire cascade; shipment pipeline; drivers/training/posture; tendering/loads/suspension cascade; placards/segregation/dispatch; security plans & routes; incidents & penalties).
- §4. Endpoint Definitions — 66-row, 4-column table; all rows verified against scaffold.
- §5. Error Code Catalogue — 66-row, 2-column table; all statuses verified against scaffold.

**Zero-Silence coverage audit (Contract 2):** every scaffold rule traced to PRD prose — all 14 state machines' transitions (from/to, preconditions with error IDs, side effects incl. all multi-link cascades); all 11 calculations (registration_fee provisional/final variants with tier constants, surcharge, late-fee months semantics, discount bands, processing-fee bracket pinned on pre-fee subtotal; incident_penalty reported/confirmed variants with inclusive deadline boundaries; placard_determination with 454.0/2270.0 inclusive thresholds and DANGEROUS substitution conditions; total_table2_weight live aggregation; load_handling_fee per-line rounding; segregation_check class/group pairs incl. CLASS_1_* expansion; training_expiry_extension with tie-break and both-inclusive 90-day window plus one-second-after case; driver_qualification_posture ordered branches with strict/inclusive boundary notes; security_plan_selector eligibility/ranking/tie-break/empty-set; payment_waterfall ordering never-by-id and credit-first; safety_rating_update points and floor; outstanding_balance OPEN-only); all 22 validation rules with priority ordering stated where multiple share an endpoint; both OCC rules; all endpoint side effects; all field defaults/initials; sibling-branch symmetry (submit ×3 sources, cancel ×3 sources, certify ×2, file-written ×2, void ×2).

**Hard contract reports:**
- Contract 1 (Field-Name Coverage): entities[].fields 91/91, request_body 58/58, query_params 15/15 — **PASS** (three misses — `kind`, `load_id`, `vehicle_class` — found and repaired in a second pass)
- Contract 2 (Rule Coverage): all categories expressed, 0 missing — **PASS**
- Contract 3 (§3 Path Purity): 548 §3 backtick tokens, 0 path/method violations — **PASS**

Note: `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, per the constraint.

## Step 5: Generate unit tests — 2026-08-10T19:20:00.000Z

All work is complete and verified on disk. Final summary:

## Generated files

**test_helpers/** (9 files, all under `/home/ubuntu/github/CodingPRD/tasks/task_1116_hazmat_transportation_compliance/test_helpers/`):
- `types.py` — 15 status/field enums, 16 entity TypedDicts (TrainingRecord/LoadItem correctly omit `updated_at`/`version` per PRD §2.5)
- `api_client.py` — `ApiClient(GenericApiClient)` with 51 methods, one per PRD §4 endpoint
- `api_errors.py` — 69 `ApiErrorId` members + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` + carrier balance invariants
- `factories.py`, `constants.py` (fee/penalty/placard thresholds), `test_users.py` (opaque roles + per-user officer builders for SoD), `fixtures.py` (5-tier composites: `create_approved_carrier_paid`, `create_documented_shipment`, `create_sealed_load_with_tendered_shipment`, `setup_dispatchable_scenario`, `create_qualified_driver`, `pay_outstanding`, `set_clock`, …)

**test_suite/** (9 files): `conftest.py` + 8 test files — `test_01_carrier_registration_fees.py`, `test_02_shipment_pipeline.py`, `test_03_loads_placards_segregation.py`, `test_04_dispatch_and_cascades.py`, `test_05_tender_gates_drivers_windows.py`, `test_06_payments_invoices.py`, `test_07_incidents.py`, `test_08_api_contracts.py`.

## Coverage

- **Queue A (Difficulty): 20/20 instances translated**, each with exactly 2 tests (40 tests). **0 skipped.**
- **Queue B (Corner): 38/38 non-stub instances translated** (≥1 test each; 42 tests). **0 skipped.** The 7 `excluded_because:` stubs were not translated; all their `difficulty_instance` cross-references verified to resolve.
- Every non-stub instance passed the PRD-first two-condition filter (this PRD covers all scaffold rules verbatim, including validation ordering in §2.8 and gate ordering in §3.6). One deliberate omission: for `carrier_create_applies_defaults` I did not assert `version == 1` — the PRD never pins the initial version value (only "+1 per mutation"), so that sub-claim fails the two-reader test; all PRD-pinned defaults (DRAFT, 100, 0, false, nulls) are asserted.

## Verification

- `python3 -m py_compile` — all 18 files compile.
- `pytest --collect-only` — **82 tests collected cleanly** (import of `test_helpers` succeeds with the framework installed).
- Automated audit: all 20 difficulty tags have ≥2 tests, all 38 corner tags have ≥1, no phantom tags, every test docstring ends with exactly one `Design: Difficulty/...` or `Design: Corner/...` line resolving to a real instance, every quoted PRD citation contains a verbatim whitespace-normalized match in PRD.md, and no `skip`/`skipif`/`xfail` markers exist anywhere.

## Step 6: Generate implementation — 2026-08-10T19:20:00.000Z

All 66 hazmat endpoints registered (the 67th rule is Flask's built-in `/static` route, which is never hit under `/hazmat`). Implementation complete and boot-verified.

## Summary

**File list** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1116_hazmat_transportation_compliance/workspace/implementation/`):
- `start.sh` — guarded pip install (`import flask` check), `exec python3 app.py` in foreground
- `requirements.txt` — flask>=3.0
- `app.py` — Flask app, 12 blueprint registrations, envelope-shaped 404/405/500 handlers
- `db.py` — in-memory store (13 dicts, starts empty, no seeding), logical clock (default exactly `2026-05-01T00:00:00Z`), datetime helpers (second-granularity parsing, `.000Z` formatting, calendar month/year arithmetic, `months_late`), clock sweep
- `errors.py` — ApiError + full error-ID catalog
- `envelope.py` — `meta`/`response_type`/`data` envelope, pagination fields in meta
- `validators.py` — X-User-ID/X-User-Role auth (400) + role gate (403) decorator, request-shape validators, pagination (limit 1–100 default 10, offset ≥ 0)
- `listing.py` — created_at-ASC ordering + paginated list responses
- `calc.py` — all 12 calculation rules with Decimal half-up per-component rounding
- `serializers.py` — exact field sets (versioned resources carry id/created_at/updated_at/version; TrainingRecord & LoadItem carry only id/created_at)
- `routes/`: `clock_routes.py`, `carriers.py`, `invoices.py`, `plans.py`, `catalog.py` (materials + specs), `drivers.py`, `vehicles.py`, `shipments.py`, `papers.py`, `loads.py`, `routes_routes.py`, `incidents.py`

**Endpoint count:** 66/66 (method, path) pairs from SCAFFOLD §1.5 / PRD §4.

**State machines implemented:** Carrier (DRAFT→SUBMITTED→APPROVED_ACTIVE→SUSPENDED/EXPIRED, reinstate, clock-sweep expiry), SecurityPlan (submit/approve/reject/revise + sweep expiry, version bumps stale pins), PackagingSpec (retire cascade → shipment cancel → paper void), Driver (system-only suspend/reinstate cascades), Vehicle (AVAILABLE/LOADING/DISPATCHED derived), Shipment (full pipeline incl. reject/rework loop, re-tender self-loop, PATCH reverts to DRAFT on classification-relevant change), ShippingPaper (certify/amend/lock/void with amendment_count), VehicleLoad (seal/unseal/dispatch/arrive/void with 3-link dispatch cascade), IncidentReport (phone→written→close, MINOR direct-file exception), RegistrationInvoice (waterfall PAID, void).

**Calculations implemented:** registration_fee (tiered SMALL/MEDIUM/LARGE, 50% security surcharge, 10%/mo capped 50% late fee, 5%/2.5% safety discount on final variant, 3%-vs-2500 processing fee bracketed on pre-fee subtotal), payment_waterfall (credit-first, assessment_year/created_at ordering), incident_penalty (reported + confirmed variants with ±50% adjustment, 12h phone / 30d written deadlines, 5000/day capped 500000), placard_determination (TABLE_1 always, TABLE_2 at ≥454.0 kg, DANGEROUS substitution at ≥2270 kg with ≥2 classes), load_handling_fee (per-line 6.25% round-then-sum + 725/placard), segregation_check (CLASS_1_*/5_1, 5_1/3, 2_3/3; SG_ACID/ALKALI, SG_OXIDIZER/FLAMMABLE), training_expiry_extension (90-day inclusive window anchoring), driver_qualification_posture (strict endorsement expiry, inclusive training expiry), security_plan_selector (approved_at DESC, created_at ASC), safety_rating_update (2/10/25, floor 0), outstanding_balance (OPEN invoices only).

**Key precedence decisions:** PRD prose won over scaffold `validations[].priority` where they conflicted — tender gates ordered carrier→state→plan→driver-FK→qualified→fiscal per §3.6; seal ordered STAGING→EMPTY→carrier→segregation and dispatch ordered SEALED→TENDERED→route-window→corridor→pins→carrier→vehicle per §3.7. OCC (`expected_carrier_version`, `expected_shipment_version`) is a required shape field, checked at priority 6 before from-state gates per §2.8.

**Boot verification:** `PORT=<port> bash start.sh` boots cleanly from a fresh process; auth-missing request returns envelope `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (400); unknown path returns envelope `ERR_NOT_FOUND`; after kill+restart the store is empty (`total_count: 0`). Three smoke suites passed: full pipeline (create→submit→approve→pay→classify→verify→certify→document→tender→load→seal→dispatch→arrive, exact fee math 27500/40000/149350/410713 verified), DANGEROUS substitution + stale-plan/re-pin + route-window gates, training anchoring boundaries, endorsement exact-instant boundary, early/late renewal math (40000 and 51250 with months_late=3), suspend 3-level cascade, reinstatement flat 75000, waterfall with credit carryover, and SoD 403. All failures observed during testing traced to my test scripts (wrong operation order, stale clock across suites), never to the implementation.

## Step 7: Run tests and iterate — 2026-08-10T19:35:00.000Z

Orchestrator ran the first 8-round parallel sweep directly (sweep.sh; verbatim start command `cd .../workspace/implementation && bash start.sh`); route parity pre-verified 66/66 (only extra route = Flask built-in /static). First sweep: 78/82 ×5 rounds, 77/82 ×3 rounds; union of 6 failing tests (4 deterministic, 2 flaky). One long-lived diagnostic subagent then owned diagnose→fix→rerun. Its summary verbatim:

Sweep complete. All 8 rounds pass 82/82.

## Status summary

**Iteration results**
- Before: 78/82, 78/82, 78/82, 77/82, 78/82, 77/82, 77/82, 78/82
- After: **82/82 in all 8 rounds** (passed == total in every results file)

**Tests deleted**: none.

**Root-cause diagnoses and fixes**

1. **Three deterministic timestamp-format failures** (test_01 `test_incident_penalty_reported_variant_computed_at_file_written`, test_05 `test_training_expiry_anchored_at_window_edge`, test_07 `test_written_deadline_inclusive_boundary`):
   - STEP 1a/1b finding: PRD §2.4 mandates the three-fractional-digit serialization verbatim only for `created_at`, `updated_at`, and `api_request_timestamp`. For computed datetime fields (`phone_deadline`, `written_report_deadline`, `expires_at`) the PRD specifies only the *instant* ("twelve hours after `occurred_at`", "thirty days after `occurred_at`", "prior `expires_at` plus three years") and states "Datetimes elsewhere in the system are compared at one-second granularity." The exact string format is PRD-silent → non-unique derivability (a faithful implementer may emit `...T12:00:00Z` or `...T12:00:00.000Z`; the implementation chose the latter uniformly). Per STEP 1c partial coverage, the covered assertion (exact instant) was kept and the uncovered assertion (exact string format) removed — no test deletion needed since the instant assertions are the load-bearing ones.
   - **test_helpers/assertions.py**: added `assert_same_instant(actual, expected)` — parses both sides and compares UTC instants at one-second granularity, with a docstring tracing to the PRD sentences above.
   - **test_suite/test_01_carrier_registration_fees.py**, **test_05_tender_gates_drivers_windows.py**, **test_07_incidents.py**: converted the 6 exact-string datetime assertions (`phone_deadline`, `written_report_deadline`, three `expires_at`) to `assert_same_instant`; imported the helper. These were the only exact-string datetime assertions in the entire suite.

2. **test_08 `test_category_not_authorized_rejected`** (deterministic NameError): pure test_suite bug — `create_packaging_spec` was used at line 397 but missing from the file's import list. Fixed by adding it to the `from test_helpers import (...)` block in **test_suite/test_08_api_contracts.py**. The fixture itself is PRD-faithful (§3.4 category gate).

3. **Two flaky placard tests** (test_03, rounds 4/6/7): not a product or fixture bug. Failures were infrastructure-level — "API server could not be restarted" setup errors and one connection reset — caused by host load from 8 concurrent rounds × per-test server reboots. The tests' assertions trace verbatim to PRD §3.7 ("reaches at least 454.0 kg — the boundary is inclusive"); `start.sh` already guards against pip-install boot contention, and `app.py` boots with no seeding. No code change warranted; the rerun confirmed zero recurrence.

**Implementation layer**: untouched — no fix was warranted there; the implementation's uniform three-fractional-digit datetime serialization is a PRD-consistent choice, and no PRD-required check was weakened.

**All 8 rounds now pass: yes.**

Orchestrator disk verification after subagent exit: all 8 results.{1..8}.json fresh-stamped, each passed=82 failed=0 errors=0 total=82 → ALL_CLEAN.

## Step 8: Finalize PRD — 2026-08-10T19:44:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1116_hazmat_transportation_compliance/workspace/PRD_FINALIZED.md` written with exactly one inline revision; everything else in PRD.md is verbatim.

## Line counts
- PRD.md: 341 lines; PRD_FINALIZED.md: 341 lines (single long line 86 replaced in place; +0 lines, +0.0% line delta; the changed line grew by one sentence).

## Changes
- **§2.5 — revise (line 86)** — inserted one sentence after the `created_at`/`updated_at` sentence pinning that every non-null datetime the server emits in a response uses the same three-fractional-digit ISO 8601 UTC serialization (e.g. `2026-06-01T12:00:00.000Z`), explicitly covering computed datetimes (`phone_deadline`, `written_report_deadline`, training-record `expires_at`), echoed supplied datetimes (`hazmat_endorsement_expires_at`, `effective_from`, `effective_to`, `planned_departure_at`, `planned_arrival_at`, `occurred_at`), and clock-derived stamps (`registration_expires_at`, `approved_at`, `phone_reported_at`, `written_filed_at`) — `implementation/db.py:61-65` (`fmt_dt`), `implementation/serializers.py:207-208,100` and all other serializer datetime lines, `implementation/routes/clock_routes.py:21`, `implementation/envelope.py:18`.

## Step-7 items disposition
- `assert_same_instant` helper + 6 converted assertions (test_01, test_05, test_07) — the one PRD silence (computed-datetime string format); resolved by the single edit above.
- `test_08_api_contracts.py` missing `create_packaging_spec` import — pure test bug (NameError), no PRD semantics; no edit.
- Flaky placard tests (test_03) — infrastructure restart failures under concurrent load, no code/PRD content; no edit.

## Per-edit pre-edit search log (Edit 1, the only edit)
- **(a) Subject:** serialization string format of datetime values emitted in API responses (Step 7 found PRD pinned the three-fractional-digit format only for `created_at`, `updated_at`, `api_request_timestamp`, leaving computed datetimes unpinned; impl emits the same format uniformly).
- **(b) Impl paths enumerated and read/grepped:**
  - `implementation/db.py:44-65` — `parse_dt` (zeroes microseconds on all input) and `fmt_dt` (sole entity-datetime serializer, `YYYY-MM-DDTHH:MM:SS.mmmZ`, `None`→`null`); `db.py:97-117` `stamp_new`/`stamp_new_light`/touch stamp from `store.clock`, so every stored/emitted datetime has zero microseconds.
  - `implementation/serializers.py` (whole file) — every datetime field of all 13 serializers routes through `fmt_dt`: carrier (18,23,24), security_plan (35,36,38-40), material (59,60), spec (73,74), driver (85,88,89), training_record (99,100,102), vehicle (113,114), shipment (134,135), shipping_paper (151,152), vehicle_load (162,163,168,169), load_item (180), route (190-193), incident (203,207-210,215,216), invoice (232,233).
  - `implementation/routes/clock_routes.py:21` — clock endpoint's `current_utc` via `fmt_dt`.
  - `implementation/envelope.py:18` — `api_request_timestamp` via byte-identical inline format.
  - Repo-wide greps over `routes/*.py`, `listing.py`, `validators.py`, `app.py`, `calc.py`, `errors.py` for `isoformat|strftime|format(|str(` and f-string message construction — no datetime emission path outside `fmt_dt`/envelope, and no error `message` embeds a datetime value.
  - `test_helpers/assertions.py` `assert_same_instant` docstring confirms the PRD-silence framing.
- **(c) Wording adjustment:** widened from naming only the three Step-7 computed fields to "every non-null datetime the server emits in a response," because the universal claim was verified true on every enumerated path (all via `fmt_dt` or the identical envelope format) and prevents fresh-implementer divergence on unexercised fields (`effective_from`, `planned_departure_at`, `registration_expires_at`, `current_utc`, etc.); added the "non-null" qualifier because nullable fields (`registration_expires_at`, `approved_at`, `phone_reported_at`, `written_filed_at`) serialize as `null` when unset (`fmt_dt` returns `None`), so an unqualified "every datetime" would mis-describe those paths.

## Step 9: Complete PRD — 2026-08-10T19:55:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1116_hazmat_transportation_compliance/workspace/PRD_COMPLETED.md` produced (copied from `PRD_FINALIZED.md`, then edited in place; no sections added or removed).

## Size delta
- Source `PRD_FINALIZED.md`: 341 lines, 53,741 chars
- `PRD_COMPLETED.md`: 345 lines, 57,180 chars
- Delta: +4 lines, +3,439 chars (21 diff hunks, all in-paragraph inserts/revisions plus two table rows)

## Counts
- Ambiguity-pins: 25
- Mismatch-revisions: 4

## Changes

- §2.2 — insert — ambiguity — generic fallbacks: undefined path → `ERR_NOT_FOUND` 404, unsupported method → `ERR_NOT_FOUND` 405, unexpected failure → `ERR_INTERNAL` 500 — implementation/app.py:53-66
- §5 — insert — ambiguity — catalogue rows for `ERR_NOT_FOUND` (404/405) and `ERR_INTERNAL` (500) — implementation/app.py:53-66
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` → `ERR_INVALID_REQUEST` (400) — implementation/validators.py:140-152
- §2.3 — insert — ambiguity — `has_more` true exactly when `offset` + rows in returned page < `total_count` — implementation/envelope.py:33
- §2.3 — insert — ambiguity — `created_at` ordering ties break by creation (insertion) order — implementation/listing.py:10, db.py:120-121
- §2.4 — insert — ambiguity — clock set accepts past or future targets, sets verbatim, fires sweep, responds with `data: {"current_utc": ...}` — implementation/routes/clock_routes.py:14-21
- §2.4 — insert — ambiguity — input datetimes parsed ISO 8601, normalized to UTC (missing offset = UTC), truncated to whole seconds; calendar month/year addition clamps day to target month's last day — implementation/db.py:44-80
- §2.5 — insert — ambiguity — `version` starts at 1 at creation; `created_at`/`updated_at` stamped from the logical clock, never wall time — implementation/db.py:97-117
- §2.8 — insert — ambiguity — `verified_fleet_size` must be at least 0 added to the shape-rule list — implementation/routes/carriers.py:142-144
- §2.8 — insert — ambiguity — endpoint-specific gate orders pinned in §3 (seal, certify) govern over the generic pipeline — implementation/routes/loads.py:202-215, routes/papers.py:65-69
- §3.1 — insert — ambiguity — `registration_tier` is null until the first submission — implementation/routes/carriers.py:64
- §3.1 — insert — ambiguity — approval recomputes the most recently created open INITIAL/RENEWAL invoice (proceeds with no invoice change if none remains open, e.g. voided); RENEWAL late fee re-evaluated against the clock at approval time — implementation/routes/carriers.py:150-170
- §3.1 — insert — ambiguity — approval re-derives `registration_tier` from `verified_fleet_size` — implementation/routes/carriers.py:166
- §3.2 — insert — ambiguity — payments accepted regardless of carrier registration status (no carrier-active gate), so a SUSPENDED carrier's reinstatement invoice is payable — implementation/routes/carriers.py:250-259
- §3.2 — insert — ambiguity — payment waterfall ties beyond `created_at` break by creation order — implementation/calc.py:141
- §3.3 — insert — ambiguity — spec `max_packing_group` restricted to PG_I/PG_II/PG_III (`PG_NONE` rejected) — implementation/routes/catalog.py:90-91, validators.py:33
- §3.3 — insert — ambiguity — retire naming a nonexistent `specId` yields `ERR_SPEC_NOT_ACTIVE` (409); no spec-specific not-found error exists — implementation/routes/catalog.py:122-125
- §3.4 — insert — ambiguity — new paper starts DRAFT with `amendment_count` 0 and `certified_by_user_id`/`er_response_guide_number` null — implementation/routes/papers.py:37-46
- §2.9 — insert — ambiguity — second shipping-paper create rejected even when the existing paper is VOIDED (at most one paper ever) — implementation/routes/papers.py:33-36
- §3.4 — insert — ambiguity — reject's optional `reason` is accepted but neither stored nor returned — implementation/routes/shipments.py:261-275
- §3.4 — insert — ambiguity — amending a classification-relevant field to an equal value is not a change (no DRAFT revert); `version` still increments — implementation/routes/shipments.py:176-195
- §3.5 — insert — ambiguity — training prior-record selection: equal `completed_at` and equal `created_at` further break by creation order — implementation/calc.py:167-173
- §3.6 — insert — ambiguity — add-item check order pinned: DOCUMENTED → segregation vs items aboard → already-loaded — implementation/routes/loads.py:147-164
- §3.6 — insert — ambiguity — remove-item with no LoadItem linking the shipment to the load yields `ERR_SHIPMENT_NOT_REMOVABLE` — implementation/routes/loads.py:186-193
- §3.7 — insert — ambiguity — seal gates evaluated in the order listed (STAGING → EMPTY → carrier-active → segregation) — implementation/routes/loads.py:202-215
- §3.7 — insert — ambiguity — stored `required_placards` emitted sorted ascending (alphabetical) — implementation/calc.py:306
- §3.9 — insert — ambiguity — incident `penalty_cents` starts at 0 — implementation/routes/incidents.py:52
- §3.9 — insert — ambiguity — `is_phone_late`/`is_written_late` are not stored booleans; computed live from recorded timestamps on every read — implementation/serializers.py:211-212, calc.py:345-356
- §3.9 — insert — ambiguity — `adjustment_percent` defaults to 0 when omitted — implementation/routes/incidents.py:121
- §2.4 — revise — mismatch — "weights are compared at one decimal of precision" → weights are exact decimal quantities, summed and compared exactly with no rounding — implementation/calc.py:280-306, routes/shipments.py:237
- §3.6 — revise — mismatch — `total_table2_weight_kg` "expressed to one decimal" → exact decimal summation with no rounding — implementation/calc.py:280-290
- §3.4 — revise — mismatch — certification checks the paper's stored `shipper_certification_signed` flag, and the paper-state gate fires before it (PRD had labeled the flag check "request-shape validation", which §2.8 places first) — implementation/routes/papers.py:65-69
- §3.8 — revise — mismatch — plan `coverage_categories` is validated only against the declared category enumeration; PRD's "a subset of the carrier's authorized categories" claim is not enforced — implementation/routes/plans.py:50-51

Everything else in the implementation (endpoint set, roles per endpoint, state machines, fee/penalty/placard formulas, cascade links, OCC guards, error catalogue, filter sets, 201/200 conventions) was already uniquely pinned by `PRD_FINALIZED.md` and required no change.
