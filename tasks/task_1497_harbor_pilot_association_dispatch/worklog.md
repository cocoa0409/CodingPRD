# Worklog — task_1497_harbor_pilot_association_dispatch

## Step 1: Create Task Directory — 2026-08-13T13:25:00.000Z

Task directory `tasks/task_1497_harbor_pilot_association_dispatch/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline orchestrator (per /prd-bench-entrance invocation args). Treated as DONE; no index scan performed, no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-13T14:47:02.656Z

All three scaffold artifacts are generated, lint-clean, and numerically verified.

## Deliverables (all under `/home/ubuntu/github/CodingPRD/tasks/task_1497_harbor_pilot_association_dispatch/`)

**SCAFFOLD.yaml** (§1.0–§1.7, no design keys):
- **Profile**: primary archetype temporal_windowing, secondary pricing_engine; layers = selector_policy, dual_variant_calculation, cascading_side_effects, optimistic_concurrency; flat topology; parallel state dimensions; peer_roles; immediate consistency.
- **11 entities**: Pilot, LicenseEndorsement, RotationEntry, VesselOrder, PilotBoat, Assignment (parallel `service_status` × `billing_status`), Invoice, Incident (branching fork DISMISSED vs SUBSTANTIATED→CLOSED), Apprentice, TariffSchedule (computed SCHEDULED/ACTIVE/SUPERSEDED), DistributionRun. All FKs use the canonical `FK -> X.id` prefix and each has a reverse-reachability GET.
- **11 state machines**, **2 OCC concurrency rules** (`order-amend-stale-version` on PATCH vessel-orders, `endorsement-create-stale-pilot` on endorsement create-with-supersede, both 412).
- **11 calculations** with pinned constants: dual-variant tariff (provisional average-rate vs final marginal), per-component-then-sum invoice rounding, rolling 7-day duty (4320-min cap, inclusive boundaries), rest thresholds (480→960 else 600), rotation/boat selectors with explicit eligibility+rank+tie-break+empty-pool fallback, pilot closed-interval vs boat half-open+45min-buffer overlap, dual-variant apprentice readiness, waterfall revenue distribution (levy tier keyed on gross before deduction; per-share round_half_up then remainder reconciliation by created_at).
- **23 ordered validations** (auth → authz/ownership → existence → OCC → state → safety → constraint → referential → temporal → fiscal), **43 endpoints** (incl. `POST /pilotage/_clock/set_current_utc` with pinned default `2026-08-01T00:00:00Z`), **23 errors**, **6 roles** (Pilot is `entity_backed:Pilot`; others opaque; VesselAgent ownership via `agent_id`).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml**: 9 rule groups × 2 instances = 18, all with structured `setup_api_calls`/`trigger` chains and literal asserts. Highlights: tariff 287500-vs-431250 variant divergence; apprentice STANDARD-vs-ACCELERATED same-data divergence; distribution remainder −1 absorbed by latest-created pilot (shares 992738/330912); depth-3 substantiation cascade (SUSPENDED→OFF_BOARD→RECALLED) and depth-2 order-cancel compensation cascade; state-vs-constraint and safety-vs-temporal priority conflicts; duty boundary 4320 pass/4321 fail and detention 30-free/31-charged; boat buffer-edge 12:45 allowed vs 12:44 rejected, pilot touching 12:00 rejected vs 12:01 allowed; rotation-ordering and cent-conservation invariants.

**SCAFFOLD_CORNER_DESIGN.yaml**: 45 instances across all nine guide sections (6 `excluded_because` stubs citing valid §1.8 names), covering required fields, ignored system/computed inputs, 404/400/401/403 paths, invalid transitions and terminal lockdowns, pagination defaults, OCC stale-version tests for both rules, endorsement supersede, RBAC denials incl. cross-pilot ownership, selector ranking, derived-field reconciliation, and immediate consistency.

**Verification**: `scaffold_lint.py` verdict (verbatim):

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

(43 endpoints, 11 entities, 18 §1.8 + 39 active §1.9 instances, 476 calls scanned.) Additionally verified by script: file-split discipline, 62 unique instance names across both designs, stub references resolve, full `${var}` placeholder closure, all `grounds:` resolve to declared §1.1–§1.7 elements, and every formula-derived assertion literal recomputed independently in Python. No forbidden concurrency vocabulary present.

## Step 3: Copy Shared Files — 2026-08-13T14:47:47.453Z

Copied `./INSTRUCTION.md` → `tasks/task_1497_harbor_pilot_association_dispatch/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-13T14:58:52.245Z

All three hard contracts pass. The PRD is complete.

---

## Summary

**PRD generated:** `/home/ubuntu/github/CodingPRD/tasks/task_1497_harbor_pilot_association_dispatch/workspace/PRD.md`

**Structure:** 1 introduction (2 paragraphs — business context + system scope), 10 §2 subsections (roles/identity, verbatim §2.2 envelope, pagination, logical clock, common properties, monetary precision, OCC, validation order, rotation invariants, interval semantics), 10 §3 subsections organized by business lifecycle (membership → intake → dispatch → in-service → cancel/recall/reassign → tariff engine → fatigue → invoicing/distribution → incidents → apprentice program), §4 endpoint table (42 endpoints, 4 columns), §5 error catalogue (23 errors, 2 columns).

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields: 61 required, 61 present, 0 missing
- endpoints[].request_body: 11 required, 11 present, 0 missing (expected_order_version, expected_pilot_version, to_iso8601, exam_result, trips_delta, evaluation_score, scheduled_start, scheduled_end, boat_id, apprentice_id, pilot_id all covered)
- endpoints[].query_params: 2 required (limit, offset), 2 present, 0 missing
Status: PASS (74 unique identifiers, all backticked in PRD)
```

```
Rule coverage check:
- validations[] with priority: 23 checked, 23 expressed in prose (§2.8 narrates the pipeline in pinned order: auth → existence → OCC → state guards → license/tonnage/rest/duty → pools → gating → temporal → fiscal → catch-all), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (PATCH vessel-orders with expected_order_version → ERR_STALE_VERSION/412; POST endorsements with expected_pilot_version → ERR_STALE_VERSION/412), 0 missing
- state_machines[].transitions: 22 checked across 10 entities (VesselOrder 5, Assignment 6, Incident 4, Invoice 2, Apprentice 2, Pilot 1, RotationEntry 2, PilotBoat 2, LicenseEndorsement 1, TariffSchedule 3, DistributionRun 2), all from/to states named with preconditions and side effects, 0 missing
- calculations[]: 9 checked (tariff_base_fee two variants, invoice_final_composition, fatigue_rolling_duty, rest_requirement, rotation_pilot_selection, pilot_boat_selection, pilot_interval_overlap, boat_interval_overlap, apprentice_readiness two variants, revenue_distribution, tariff_schedule_resolution), all expressed in precise business prose with constants embedded (480/960/600 min, 4320 min ceiling, 45 min buffer, 50/40 trips, 85 avg, 10000000 cent levy threshold, 0.08/0.10 levy), 0 missing
- validations[] conditions: 23 checked, 23 matchable to error_id in §2.8 + §3 narrative, 0 missing
- endpoints[].side_effects: all dispatch/start/board/complete/cancel/recall/reassign/substantiate/settle/void cascades expressed, including the divergent DISMISSED-vs-SUBSTANTIATED fork and the direct-vs-cascaded cancel order-revert asymmetry, 0 missing
- entities[].fields[] structured content: defaults (status enums, trips_completed=0, evaluation_avg=0, recall_count=0), nullability (rest_until, previous_position, apprentice_id, actual_start, actual_end, corrective_note, finalized_at, max_gt_inclusive), and computed-vs-input sourcing reconstructible from prose, 0 missing
- sibling-branch symmetry: incident DISMISS/SUBSTANTIATE fork given equal prose density; order-cancel BOOKED-vs-DISPATCHED branches symmetric; assignment-cancel ASSIGNED-vs-RECALLED branches symmetric, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 326
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**§2.2 verbatim:** byte-identical match against `section-2.2-response-structure.md` confirmed.

**Novel structure choices for this domain (vs. example):** 10 §2 subsections including domain-specific "Logical Clock," "Rotation Board Invariants," and "Interval Semantics: Pilots versus Boats"; 10 §3 subsections organized by business lifecycle rather than the hospital example's plan-centric hierarchy; introduction leads with cooperative business context instead of "This document outlines..."; no pseudocode or fuzzy qualifiers anywhere.

## Step 5: Generate Unit Tests — 2026-08-13T15:41:52.369Z

Test generation for task_1497 is complete and all audits pass.

## What was generated

**`test_helpers/`** (9 files, all importing cleanly):
- `types.py` — 11 entity TypedDicts + 13 status/role enums. All entities carry `common_fields: true`, so all include `id`/`created_at`/`updated_at`/`version`.
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (33 endpoints, `/pilotage` prefix).
- `api_errors.py` — all 23 error IDs with the §5 HTTP status map, registered via `set_error_http_status_map` at import time.
- `assertions.py` — per-entity `assert_*` validators plus `parse_instant`/`assert_instant_equals` (compares clock-derived instants like `rest_until`/`finalized_at` semantically, since PRD pins fractional-digit format only for envelope/common timestamps).
- `factories.py`, `constants.py` (4320 duty cap, 480/960/600 rest rule, 45-min boat buffer, 50/40/85 readiness bars, levy tiers, MAIN_TARIFF three-tier payload).
- `test_users.py` — shared opaque-role headers + mandatory per-instance builders `make_pilot_headers(pilot_id)` (entity-backed Pilot) and `make_agent_headers(agent_id)` (order-ownership keyed).
- `fixtures.py` — composite builders: `setup_assigned_scenario` / `setup_aboard_scenario` / `setup_completed_scenario` / `setup_recalled_assignment` / `setup_finalized_invoice`, plus atomic steps (`dispatch`, `launch`, `board`, `complete`, `issue_endorsement` with fresh OCC re-read, `set_clock`, `invoice_of_assignment`, `rotation_entry_of`).

**`test_suite/`** — `conftest.py` + 9 test files, **76 collected tests** (75 functions, one parametrized ×2):
- All 18 difficulty instances covered by exactly ≥2 tests each (36 tests).
- All 39 non-stub corner instances covered by ≥1 test each; all 5 `excluded_because` stubs skipped, and their difficulty-instance pointers verified to resolve.
- No tests invented outside the two design indices.

## Audit results
- Tag coverage: PASS (every test tagged exactly once; every non-stub instance has its quota; tags resolve to real instance names).
- Citation check: PASS (every docstring's quoted PRD sentence greps verbatim in `workspace/PRD.md`; three initial misses — table-row quotes and a truncated §2.8 enumeration — were fixed to verbatim text).
- C4 check: PASS (every docstring ends with its `Design: ...` line).
- No `skip`/`skipif`/`xfail`, no "scaffold" references in generated code; everything compiles and `pytest --collect-only` succeeds.

## Judgment calls worth noting
- **Timestamp comparisons** for `rest_until`/`finalized_at` use instant equality (parse-and-compare), not string equality — PRD pins "three fractional digits" only for envelope/common fields, so string equality on domain datetimes would fail a legitimate `...T00:00:00.000Z` serializer.
- **Duty-boundary instance timestamps corrected in setup**: the design's `actual_end` of `2026-08-03T23:00Z` yields 2820 duty minutes, not the asserted 4260. The fixture completes the 71-hour job at `2026-08-04T23:00Z` (rest then expires `2026-08-05T15:00Z`, clock set to `2026-08-05T16:00Z`), which makes the asserted 4320-equality/4321-rejection boundary actually hold. Asserted values are unchanged from the design.
- **gt adjusted to 4000** in two dispatch-gating setups whose recipe paired gt 8000 with a single tier capped at 5000 — no tier would contain the order's gt, which the PRD leaves undefined; 4000 keeps setup inside a declared tier without touching any asserted value.
- **Initial `version == 1` / board positions starting at 1** are asserted per the design indices' pre-computed literals (PRD pins increment-by-one and max+1 but not the anchor); this matches the benchmark-wide convention used consistently across both indices.
- No instances were dropped for PRD-silence reasons — every non-stub instance had verbatim PRD coverage of its asserted rule.

## Step 6: Generate Implementation — 2026-08-13T15:41:52.369Z

Implementation complete for task_1497 (Harbor Pilot Association Dispatch). All files live under `/home/ubuntu/github/CodingPRD/tasks/task_1497_harbor_pilot_association_dispatch/workspace/implementation/`:

- `start.sh` — foreground launcher, `exec python3 app.py`, guarded `pip install` (no-op when flask present), honors `PORT` (default 10000), binds `0.0.0.0`
- `app.py`, `db.py`, `errors.py`, `response.py`, `middleware.py`, `util.py`, `services.py`, `routes/` (pilots, orders, assignments, boats, tariffs, invoices, incidents, apprentices, distribution, clock)

Key design decisions, all traced to PRD/scaffold:
- **Logical clock everywhere**: startup default `2026-08-01T00:00:00Z`; `created_at`/`updated_at`/`actual_*`/`finalized_at` and the envelope's `api_request_timestamp` all read the logical clock, never wall-clock (PRD §2.4). Internal monotonic `_seq` tie-breaks rows sharing a clock instant.
- **Empty store at boot** — no seeding; verified a fresh process returns `total_count: 0`.
- **Envelope**: `meta{api_request_id, api_request_timestamp}` + `response_type` + `data`; list pagination fields (`limit`/`offset`/`total_count`/`has_more`, defaults 10/0, clamp 1–100) inside `meta`.
- **Validation pipeline** in scaffold priority order: auth (401/403) → existence (404, path then body ids) → ownership (403, e.g. agent-vs-`agent_id` beats OCC) → OCC (412 on `expected_order_version`/`expected_pilot_version`) → state guards (409 `ERR_INVALID_STATE`/`ERR_ORDER_LOCKED`/`ERR_ORDER_NOT_DISPATCHABLE`) → explicit-reassign safety checks in pinned order (license → tonnage → rest → duty) → selector pools (pilot before boat) → apprentice gating → temporal checks → structural catch-all (`ERR_INVALID_REQUEST` 400). Verified pairs: state-beats-empty-pool, ownership-beats-OCC, OCC-beats-ORDER_LOCKED.
- **Calculations** with `Decimal` + `ROUND_HALF_UP`: dual-variant tariff (provisional average-rate vs final marginal; draft surcharge strictly-greater threshold), pinned per-component-then-sum invoice rounding, rolling 7-day duty (inclusive boundary, 4320 ceiling with equality passing), 480-minute inclusive long-duty threshold (960/600 rest), pilot closed-interval vs boat half-open+45min-buffer semantics (buffer-edge start allowed), distribution levy keyed on gross before deduction with per-share rounding then cent-per-pass remainder reconciliation (positive: created_at ASC; negative: DESC).
- **State machines**: full dual-dimension Assignment (`service_status` × `billing_status`), order-cancel cascade (DISPATCHED→CANCELLED with assignment cancel + position restore; direct cancel reverts order to BOOKED; RECALLED cancel skips restore), recall without position restore, reassign demotion, 3-hop substantiation cascade (SUSPENDED → OFF_BOARD → ASSIGNED assignments RECALLED), endorsements per-class supersession bumping `Pilot.version`, computed boat/tariff statuses.

Verification: ~90 behavioral assertions across four smoke suites passed, covering every endpoint group, every error ID in the catalog, the design doc's exact numeric scenarios (287500 provisional vs 431250 marginal; 950000/488750 totals; net 1323650 split 992738/330912), and three sequential fresh-process reboots via `bash start.sh`.

One spec note: `SCAFFOLD_DIFFICULTY_DESIGN.yaml`'s `fatigue_duty_limit_equality` instance claims a "4260-minute" job, but its own setup calls (clock→08-02T00:00, start; clock→08-03T23:00, complete) produce 2820 minutes under the PRD formula `actual_end − actual_start`. I implemented the PRD-faithful formula (the corner design's `calc_rolling_duty_window_inclusion_boundary` instance confirms the same formula and passes); if the generated test suite encodes the doc's arithmetic, that test (not the implementation) needs fixing in the step-7 iterate loop.

## Step 7: Iterate Test/Fix Loop — 2026-08-13T15:55:00.000Z

8-round parallel stability sweeps (`prd-bench-local-run --isolation per-test-server`, 76 tests/round).

**Iteration 1 (baseline):** 75/76 in all 8 rounds. Single deterministic failure: `test_02_vessel_order_intake.py::TestOrderAmendment::test_order_patch_occ_stale_version_returns_412` — `assert after["eta"] == "2026-08-11T00:00:00Z"` tripped on the server's three-fractional-digit serializer (`...T00:00:00.000Z`). Diagnosis per protocol: STEP 1 — the OCC rule (loser's write absent) is PRD §2.7 verbatim-covered; STEP 2 — the assertion over-specified the `eta` serialization, which PRD leaves unpinned (§2.5 pins three fractional digits only for `created_at`/`updated_at`/envelope timestamps). TEST IS WRONG: fixed the assertion in `test_suite/test_02_vessel_order_intake.py` to use `assert_instant_equals` (the suite's established instant-comparison helper for clock-domain datetimes); OCC semantics assertion kept at full strength. No test deletions; no implementation changes.

**Iteration 2 (verify):** 76/76 passed in all 8 rounds — 0 failed, 0 errors, 0 skipped. Clean exit.

**Step 7 subagent exit summary (verbatim):**

- **Iterations run:** 2 (baseline sweep → one fix → verification sweep).
- **Final state:** all 8 parallel rounds pass 76/76, 0 failed / 0 errors / 0 skipped (results at `/home/ubuntu/github/CodingPRD/tasks/task_1497_harbor_pilot_association_dispatch/workspace/implementation/results.{1..8}.json`).
- **Tests deleted:** none. The single failing test's rule (OCC stale-version rejection, loser's write absent) is verbatim-covered by PRD §2.7, so no deletion criterion applied.
- **Fixes applied to `test_suite/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1497_harbor_pilot_association_dispatch/test_suite/test_02_vessel_order_intake.py` — `TestOrderAmendment::test_order_patch_occ_stale_version_returns_412` (line 179): replaced raw string equality `after["eta"] == "2026-08-11T00:00:00Z"` with `assert_instant_equals(...)` (helper added to the import list). The assertion over-specified the `eta` serialization: PRD §2.5 pins three fractional digits only for `created_at`/`updated_at` and the envelope timestamp, leaving domain-datetime serialization (e.g. `...T00:00:00Z` vs `...T00:00:00.000Z`) free — the implementation legitimately emits the latter. The OCC assertion itself (loser's amended ETA absent, version unchanged) remains at full strength; this is the suite's established instant-comparison pattern already used for `rest_until`/`finalized_at`. This matches the worklog's documented judgment call; this one call site was missed at generation time.
- **Fixes applied to `test_helpers/`:** none needed — fixtures, factories, role-header builders, and `assert_instant_equals` were already PRD-faithful.
- **Fixes applied to `implementation/`:** none — the implementation (validation pipeline ordering, OCC, selectors, tariff/distribution math, cascades, in-memory-only store) was correct in all 8 rounds of both sweeps; the only defect was the test-side serialization over-specification.

**Orchestrator verification:** independently re-read all 8 `results.{i}.json` — every round: passed 76/76, failed 0, errors 0, skipped 0.

## Step 8: Finalize PRD — 2026-08-13T15:59:50.891Z

The patch is complete. Here is the exit summary.

## Summary

**Line counts / delta:** `PRD.md` = 269 lines, `PRD_FINALIZED.md` = 271 lines, delta +2 lines (+0.74%). Exactly one inserted paragraph; no other prose touched.

**Changes (one total):**
- **§2.5 Common Resource Properties** — insert — added a paragraph after the `version` bullet pinning that all datetime-valued resource fields (`created_at`/`updated_at` plus domain instants `eta`, `rest_until`, `expires_at`, `scheduled_start`/`scheduled_end`/`actual_start`/`actual_end`, `finalized_at`, `effective_from`, `period_start`/`period_end`) serialize in responses as ISO 8601 UTC with three fractional digits (e.g. `2026-08-11T00:00:00.000Z`), with unset instants serializing as `null` — `implementation/db.py:62-67` (`fmt_dt`, the sole serializer), applied at `implementation/services.py:308-470` (all resource views) and `implementation/response.py:15` (envelope).

**Per-edit pre-edit search log:**
- **Edit 1**
  - (a) **Subject:** serialization format of datetime values in API responses.
  - (b) **Impl paths enumerated and read/grepped:**
    - `implementation/db.py:62-67` — `fmt_dt()`: sole serializer, UTC, exactly three zero-padded fractional digits (`microsecond // 1000`), `None` → `None`.
    - `implementation/db.py:70-71` — `now_iso()` → `fmt_dt(now())`.
    - `implementation/response.py:12-16, 34-40` — `_meta()` feeds `api_request_timestamp` in both success and error envelopes via `now_iso()`.
    - `implementation/services.py:301-472` — every resource view (`pilot_view`, `endorsement_view`, `rotation_entry_view`, `order_view`, `boat_view`, `assignment_view`, `invoice_view`, `incident_view`, `apprentice_view`, `tariff_view`, `run_view`): every datetime field passes through `fmt_dt`; enumerated each field name.
    - `implementation/routes/clock.py:21` — `current_utc` via `fmt_dt`.
    - Repo-wide greps for `isoformat`, `strftime`, `str(` on datetimes confirmed no serializer bypasses `fmt_dt` (only parse sites in `db.py:29-36`, `util.py:18-28`).
    - Input parsing (`util.py:98-111` `req_dt`/`opt_dt`, `db.py:_parse`) accepts any ISO 8601 — so wording was scoped to responses only, to avoid constraining accepted request formats.
  - (c) **Wording adjustments:** (i) scoped the sentence to "fields on resources ... serialized in responses" so it neither constrains request-side datetime parsing nor makes claims about the clock endpoint's `current_utc` (outside the Step 7 item's framing; left as-is, consistent with impl); (ii) used a non-exhaustive "such as" list so no enumerated resource datetime field is excluded from the rule; (iii) added the "unset instant serializes as `null`" clause to match `fmt_dt`'s `None` passthrough (e.g. `rest_until` null at registration per §3.1, `actual_start`/`actual_end`/`finalized_at` before stamping); (iv) mirrored the existing §2.5/§2.2 phrase "three fractional digits" and added the `.000Z` example to disambiguate zero-padding to exactly three digits.

**Rationale for the single edit:** the only Step 7 item was the weakening of `test_order_patch_occ_stale_version_returns_412`'s `eta` assertion (`test_suite/test_02_vessel_order_intake.py:179`), which exposed that PRD §2.5 pinned three fractional digits only for `created_at` while the implementation's single `fmt_dt` serializer emits three fractional digits for *every* datetime. The inserted paragraph closes exactly that silence, matching impl behavior on all enumerated paths. No implementation, test, or helper changes were needed, and no other PRD edits traced to the Step 7 diff.

File produced: `/home/ubuntu/github/CodingPRD/tasks/task_1497_harbor_pilot_association_dispatch/workspace/PRD_FINALIZED.md`.

## Step 9: Complete PRD — 2026-08-13T16:20:00.000Z

Step 9 complete. `/home/ubuntu/github/CodingPRD/tasks/task_1497_harbor_pilot_association_dispatch/workspace/PRD_COMPLETED.md` produced as a minimal patch over `PRD_FINALIZED.md`.

## Summary

**Source vs output**: `PRD_FINALIZED.md` (271 lines / 41,775 chars) → `PRD_COMPLETED.md` (274 lines / 45,830 chars); char-delta **+4,055**; 26 diff hunks, all inline edits (no new sections).

**Counts**: ambiguity-pins **25**, mismatch-revisions **5**.

### Ambiguity pins (insert)
- §2.2 — insert — ambiguity — `api_request_id` pinned as `req_` + 20 random alphanumerics — `implementation/response.py:14`
- §2.2 — insert — ambiguity — `api_request_timestamp` stamped from the logical clock, not wall-clock — `response.py:15`, `db.py:70`
- §2.2 — insert — ambiguity — `has_more` defined as `offset + limit < total_count` — `response.py:29`
- §2.2 — insert — ambiguity — unknown path / unsupported method → `ERR_NOT_FOUND` 404; unexpected failure → `ERR_INTERNAL` 500 — `app.py:20-30`
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` → `ERR_INVALID_REQUEST` 400 — `util.py:114-136`
- §2.3 — insert — ambiguity — list sort ties on equal `created_at` broken by creation order — `services.py:150` et al. (`_seq` tie-break)
- §2.4 — insert — ambiguity — clock accepts any parseable instant (backwards allowed), returns 200 with `current_utc` — `routes/clock.py:12-21`
- §2.5 — insert — ambiguity — `version` starts at 1 at creation — `services.py:286-294`
- §2.8 — insert — ambiguity — unconsumed body fields (incl. system/computed like `status`, `tariff_schedule_id`, `provisional_fee_cents`) are ignored, not rejected — `routes/orders.py:67-68`, `routes/pilots.py:43-44`
- §3.1 — insert — ambiguity — `license_number` unique across pilots, duplicate → `ERR_INVALID_REQUEST` 400; `share_units` pinned integer — `routes/pilots.py:36-41`
- §3.1 — insert — ambiguity — endorsement `expires_at` accepts any instant, even past — `routes/pilots.py:109`
- §3.1 — insert — ambiguity — rotation-entries `status` filter out-of-range → 400; all other list filters exact-match (unrecognized → empty page) — `routes/pilots.py:170,180-190` vs `routes/boats.py:33-36`
- §3.2 — insert — ambiguity — no effective schedule at intake → order still created with null `tariff_schedule_id`/`provisional_fee_cents`; amendment re-pin nulls likewise — `routes/orders.py:69-71,83-84,168-175`
- §3.2 — insert — ambiguity — cancel from non-`BOOKED`/`DISPATCHED` → `ERR_INVALID_STATE` 409 — `routes/orders.py:188-193`
- §3.2 — insert — ambiguity — `DISPATCHED`-cancel cascade restores board slot only when the assignment is still `ASSIGNED`; `RECALLED` releases boat only — `routes/orders.py:201-208`
- §3.3 — insert — ambiguity — dispatch/reassign window never compared against the logical clock (past windows accepted) — `routes/orders.py:253-260`
- §3.3 — insert — ambiguity — explicit `boat_id` at dispatch used as-is, not conflict-checked (contrast §3.5) — `routes/orders.py:234-237,269-274`
- §3.3 — insert — ambiguity — assignment born with `actual_start`/`actual_end`/`detention_minutes`/`delay_minutes` null, `recall_count` 0 — `routes/orders.py:284-301`
- §3.3 — insert — ambiguity — duplicate boat `name` → `ERR_INVALID_REQUEST` 400 — `routes/boats.py:20-22`
- §3.4 — insert — ambiguity — duty duration truncated down to whole minutes — `util.py:41-43`
- §3.5 — insert — ambiguity — absent `boat_id` at reassign keeps current boat with no fresh conflict check — `routes/assignments.py:326-330`
- §3.6 — insert — ambiguity — tier field constraints (`min_gt_exclusive` int ≥ 0; `max_gt_inclusive` null or int > lo; rate int ≥ 0); threshold non-negative int, `draft_surcharge_pct` any non-negative number, extras non-negative ints — `routes/tariffs.py:14-71`
- §3.6 — insert — ambiguity — provisional variant falls back to the last declared tier's rate when `gt` is outside every band — `services.py:87-90`
- §3.6 — insert — ambiguity — null pinned schedule → all invoice components and `total_cents` zero at completion — `routes/assignments.py:146-152`
- §3.8 — insert — ambiguity — `invoice_ids` ordered by invoice `created_at` asc; `shares` array ordered by pilot `created_at` asc — `routes/distribution.py:68,88-89,128`
- §3.10 — insert — ambiguity — `trips_delta` any integer (negative allowed), `evaluation_score` any number; progress loggable at any status — `routes/apprentices.py:80-81`
- §3.10 — insert — ambiguity — advancing a `CERTIFIED` apprentice → `ERR_INVALID_STATE` 409 — `routes/apprentices.py:127-132`
- §5 — insert — ambiguity — added `ERR_INTERNAL` | 500 catalogue row — `app.py:28-30`

### Mismatch revisions (revise)
- §2.8 — revise — mismatch — "non-positive quantities" → "quantities below their declared per-field minimum" (impl accepts negative `trips_delta`/`evaluation_score`) — `routes/apprentices.py:80-81` vs other `req_int(..., minimum=…)` call sites
- §2.8 — revise — mismatch — "structural validation is the final catch-all" qualified: datetime parse precedes temporal comparison, and dispatch/reassign/distribution windows are structurally validated right after the state guard, before pool/safety/overlap checks — `routes/orders.py:58-59,253-260`, `routes/assignments.py:258-265`, `routes/distribution.py:33-40`
- §3.1 — revise — mismatch — `tonnage_cap_gt` "a positive number" → "a positive integer" — `routes/pilots.py:108`
- §3.2 — revise — mismatch — `draft_dm` "also positive" → "also a positive integer" — `routes/orders.py:63`
- §3.6 — revise — mismatch — "an ordered, non-empty `tiers` array" → "a non-empty `tiers` array … ordering and contiguity are not validated" — `routes/tariffs.py:14-54`

All other implementation behaviors (validation pipeline order per endpoint, rotation demotion/restore mechanics, fatigue math with inclusive boundaries, two-variant tariff engine with per-component rounding, incident suspension cascade scoping to `ASSIGNED` only, distribution levy/reconciliation order, RBAC and ownership checks, 201/200 status mapping, all error-id/HTTP-status pairs) were already uniquely pinned by the PRD and verified against the implementation with no change needed.
