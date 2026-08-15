# Worklog — task_1770_farm_grain_storage_bin_management

## Step 1: Create Task Directory — 2026-08-14T14:49:00.000Z

Pre-assigned task directory `tasks/task_1770_farm_grain_storage_bin_management/` with `workspace/` subdirectory verified to exist. Step 1 treated as DONE per pipeline instructions; no index scan performed, no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-14T15:56:00.000Z

Scaffold generation complete. All three artifacts are written and the official linter passes clean.

## Files written
- `/home/ubuntu/github/CodingPRD/tasks/task_1770_farm_grain_storage_bin_management/SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1770_farm_grain_storage_bin_management/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_1770_farm_grain_storage_bin_management/SCAFFOLD_CORNER_DESIGN.yaml` — single top key `scaffold_corner_design`

## Counts
- Entities: **13** (Bin, GrainLot, TemperatureReading, SpoilageAlert, FumigationRecord, BinEntryPermit, StorageContract, LoadOut, Applicator, InsurancePolicy, InsuranceClaim, StorageAssessment, ShrinkEvent)
- State machines: **9** — incl. posture-driven Bin (cyclic SOUND/WATCH/ALERT/FUMIGATION_LOCKOUT), LoadOut parallel dims (transport × settlement with HELD⇄SCHEDULED cycle), StorageContract with FULFILLED→DELIVERING revert
- Calculations: **10** — 3 dual-variant (shrink provisional-vs-settlement, indemnity SPOT-vs-CONTRACT_AVG, carry CASH-vs-ECONOMIC), combinatorial modes (a) risk score, (b) per-ticket rounding order, (c) fee-tier evaluation-order pin
- Endpoints: **38** (flat topology under `/grain`, plus `/_clock/set_current_utc` with the mandated 2026-08-01T00:00:00Z default)
- Error catalog: **30** codes; **31** strictly-ordered validation rows (authn → authz/SoD → existence → OCC(412) → shape → state → safety → temporal → constraint → referential → fiscal)
- RBAC: **4** roles, segregation-of-duties model (fumigation apply≠clear via entity-backed Applicator; permit request≠approve); **1** OCC concurrency rule (`expected_contract_version` on loadout create)
- §1.8: **20 instances** across all 9 rules (every rule ≥2; Rule 2 and Rule 7 carry 3)
- §1.9: **54 active instances + 17 excluded_because stubs** (71 total) across all 9 guide sections
- Lint: `VERDICT: clean lint` — 479 recipe calls checked, all FK reverse-reachability satisfied

## Difficulty highlights (per the "harder than expert" request)
- Depth-4 cascade (reading→alert→posture→loadout HELD→contract committed release) and a depth-3 settlement cascade from a different trigger
- Every numeric assert in §1.8/§1.9 was pre-executed in Python (e.g., settlement net 4,231,395¢; fee-tier order proof 3,752 vs wrong-order 5,002; rounding-order proof 195.94 vs 195.95; 98% boundary where both contracts display ratio 0.9800 but only one FULFILLS; carry CASH +952/HOLD vs ECONOMIC −3,227/SELL)
- Two interval-overlap geometries on different resources (half-open loadout windows on Bin vs closed fumigation occupancy on Applicator) and two compensating invariants (bushels and dollars), each replay-verified end-to-end from empty DB

One authoring note: lint check (f) forced single-resource GETs for every FK-bearing child, which pushed the endpoint count to 38 — above the Expert band's 32 guideline (a guideline, not a hard rule) but required for mechanical compliance.

## Step 3: Copy Shared Files — 2026-08-14T15:58:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1770_farm_grain_storage_bin_management/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T16:05:00.000Z

All checks pass. The PRD is complete.

## Summary

**Output file:** `/home/ubuntu/github/CodingPRD/tasks/task_1770_farm_grain_storage_bin_management/workspace/PRD.md` (285 lines)

**Section overview**
- **§1 Introduction** — 2 paragraphs framing the on-farm storage problem (shrink, hotspots, delivery windows, safety lockouts) and the system scope, ending on the logical-clock determinism note.
- **§2 Global Specifications (9 subsections)** — 2.1 RBAC with all 4 roles and per-role `X-User-ID` identity semantics (opaque vs `entity_backed:Applicator`); 2.2 response envelope **emitted verbatim** (verified byte-identical against `section-2.2-response-structure.md`); 2.3 pagination (limit 10/1/100, offset 0, `created_at` ascending); 2.4 logical clock (startup default `2026-08-01T00:00:00Z`, never wall-clock, `to_iso8601`/`current_utc`); 2.5 common resource properties including the three immutable log entities (TemperatureReading, StorageAssessment, ShrinkEvent) that carry only `id`+`created_at`; 2.6 precision/rounding rules; 2.7 posture derivation ladder with exact 40.00/70.00 thresholds, gate/release cascades, and the `WATCH`→`WATCH` self-loop; 2.8 OCC (`expected_contract_version`, `ERR_STALE_CONTRACT_VERSION`/412, no other endpoint takes a version); 2.9 flat-topology left-to-right lookup and the full validation precedence layer order.
- **§3 Business Logic (9 subsections)** — site setup/lots + provisional shrink; monitoring/risk score/hotspot alerts; fumigation + REI + SoD; entry permits; contracts + load-out scheduling (OCC, window containment, half-open overlap, remaining-bushel check); dispatch/deliver/settlement (pinned per-ticket rounding, waterfall, tiered fee on pre-fee value, 98% fulfillment in bushels, void reversal); monthly assessment epoch (3/4/5-cent tiers on pre-loss balance, 0.20% invisible loss, all four sweeps, audit counters); insurance (SPOT/CONTRACT_AVG with empty-pool fallback, cap-before-deductible); carry analysis (CASH vs ECONOMIC, strictly-positive HOLD).
- **§4 Endpoint table** — 38 rows, 4 columns only. **§5 Error catalogue** — 30 rows, 2 columns only.

**Coverage audit (Hard Contracts)**
- **Contract 1 — Field coverage: PASS.** 122/122 required identifiers (all entity fields, all endpoint input/query params, scale-ticket item fields `ticket_no`/`gross_bu`/`moisture_pct`, carry-analysis response keys, clock I/O fields) appear verbatim in backticks; verified mechanically against parsed scaffold YAML.
- **Contract 2 — Rule coverage: PASS** (manual walk of all six categories): all 31 validations expressed with their `error_id` and per-endpoint `applies_to` scopes, priority orderings stated both globally (§2.9 layer order) and per endpoint chain (loadout create, permit approve, fumigation clear/create, claim submit/approve, confirm-settlement, lot fill); the 1 OCC rule names endpoint-by-framing, field, error, and status; all 10 calculations rendered as reconstructible prose (no pseudocode, no fuzzy words — the single "about" hit is non-approximating usage); all state-machine transitions covered including `ALERT`→`FUMIGATION_LOCKOUT` permit voiding and `HELD`→`EXPIRED` carrying no commitment release; sibling branches symmetric; every endpoint side-effect cascade enumerated.
- **Contract 3 — §3 path purity: PASS.** 530 backtick tokens scanned in §3; zero paths, zero bare HTTP methods, zero method+path combos.
- Supporting checks: all 30 error IDs appear in §2/§3 prose; all 4 role names exact; all enum/state values present (47 checked); §4 row count 38/38; §5 row count 30/30; §2.2 verbatim block byte-identical.

The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened or referenced.

## Step 5: Generate Unit Tests — 2026-08-14T16:26:00.000Z

Clean: no scaffold references, no skip/xfail marks, all imports work. Final summary:

## Summary

### Files written

**`test_helpers/` (9 files)**
- `__init__.py` — barrel export (framework generics + PRD-specific names)
- `types.py` — 4 role + 13 entity/status enums; 14 entity TypedDicts (correctly branching on `common_fields`: `TemperatureReading`, `StorageAssessment`, `ShrinkEvent` omit `updated_at`/`version`)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (30 endpoint methods including `_clock/set_current_utc`)
- `api_errors.py` — `ApiErrorId` enum (30 codes) + `set_error_http_status_map` registration
- `assertions.py` — per-entity `assert_*` helpers
- `factories.py` — payload factories for all 11 creatable entity types + deliver payload
- `constants.py` — domain thresholds (shrink factor, hotspot deltas, REI hours, tier floors, etc.)
- `test_users.py` — shared `TEST_USERS` for the four roles plus per-instance `make_*_headers` builders (mandatory for entity-backed `CertifiedApplicator`)
- `fixtures.py` — tiered composite fixtures: single-entity creators, `setup_bin_with_lot`, `setup_bin_lot_contract[_loadout]`, lifecycle shortcuts `setup_dispatched_loadout` / `setup_delivered_loadout` / `setup_settled_loadout`, plus hotspot-alert and fumigation helpers

**`test_suite/` (17 files: conftest + 16 test modules)**
- `conftest.py` — session-scoped `api` fixture + per-role header fixtures
- `test_01_dual_variant_shrink.py` … `test_16_corner_cross_cutting.py`

### Test counts
- **Queue A (Difficulty):** 40 tests — all 20 instances covered with exactly 2 tests each (meets ≥2 target)
- **Queue B (Corner):** 54 tests — all 54 non-stub instances covered with 1 test each (meets ≥1 target)
- **Total: 94 tests**

### Skipped instances
None. Every difficulty instance passed the PRD-first two-condition filter; every corner stub (`excluded_because`) was correctly left untranslated per §2.1 (10 stubs: `loadout_hold_release_cycle_via_posture`, `contract_fulfilled_revert_covered`, `hotspot_cascade_covered`, `rounding_order_covered`, `shrink_divergence_covered`, `indemnity_divergence_covered`, `fulfillment_tolerance_covered`, `state_beats_safety_covered`, `safety_beats_fiscal_covered`, `posture_gate_covered`, `rei_boundary_covered`, `overlap_rules_covered`, `active_fumigation_gate_covered`, `alert_loss_gate_covered`, `error_catalog_safety_and_priority_covered`, `hotspot_cascade_layer_covered`, `threshold_boundaries_covered`).

### Stage 2 self-check
- **Tag validity:** every test's docstring ends with exactly one `Design: Difficulty/<rule_id>/<instance>` or `Design: Corner/<section>/<instance>` line; all 94 tags resolve to real instances in the source YAMLs; no stub tags emitted; no dual-tagging.
- **Coverage:** all 20 difficulty instances ≥2 tests; all 54 non-stub corner instances ≥1 test. Audit script confirms zero gaps.
- **PRD citations:** every test carries at least one ≥40-char verbatim substring that survives a literal `grep` of PRD.md (whitespace-normalized). One capacity-rule citation initially ended `).` while PRD reads `); a` — fixed to match PRD verbatim.
- **No scaffold leakage:** `grep -rni scaffold` over `test_helpers/` + `test_suite/` returns zero hits.
- **No skip/xfail:** zero occurrences.
- **Import sanity:** `import test_helpers` succeeds; framework `ApiErrorId` registry contains all 30 PRD errors.

## Step 6: Generate Implementation — 2026-08-14T16:50:00.000Z

The implementation is complete and verified. Final summary:

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_1770_farm_grain_storage_bin_management/workspace/implementation/`)

- `start.sh` — guarded pip install (no-op once flask present), `exec python3 app.py`, foreground
- `requirements.txt` — `flask>=2.2`
- `app.py` — Flask entry, envelope-wrapped error handlers, binds `0.0.0.0:$PORT` (default 10000)
- `db.py` — in-memory dicts keyed by id + insertion sequence; empty on every boot, no seeding
- `clock.py` — logical clock starting at exactly `2026-08-01T00:00:00Z`, never wall-clock
- `errors.py` — all 30 catalog error IDs with exact HTTP statuses
- `response.py` — scaffold envelope (`meta`/`response_type`/`data`; list meta carries `limit/offset/total_count/has_more`)
- `middleware.py` — `X-User-ID`/`X-User-Role` auth (401/403)
- `util.py` — shape validators (Decimal-quantized bushels 2dp / moisture 1dp), FK resolution, pagination
- `services/core.py` — posture engine with gate/release cascades, spoilage risk score, contract aggregates, monthly assessment epoch, all serializers
- `routes/` — 12 modules: bins, lots, readings, alerts, fumigations, permits, contracts, loadouts, insurance (policies+claims), applicators, assessments, clock

## Endpoint count: 38/38 implemented (verified registered)

## PRD interpretation decisions (where the PRD admitted multiple readings)

1. **Timestamps**: all server-generated timestamps (`created_at`/`updated_at`, `closed_at`, `cleared_at`, `current_utc`, `api_request_timestamp`) derive from the logical clock in `%Y-%m-%dT%H:%M:%S.000Z` form — honoring "never falls back to wall-clock under any circumstance" plus the 3-fractional-digit rule (matches the passing task_1277 convention).
2. **Contract aggregates**: `committed_bu`/`delivered_bu`/`settled_value_cents`/`fulfillment_ratio` are computed on read from loadouts per their PRD definitions (so DISPATCHED→DELIVERED automatically drops commitment); `contract.version` bumps only on documented mutation events (+1 per loadout create/confirm/void, +1 per held/released/SCHEDULED-expired loadout, +1 per sweep transition).
3. **Future-start fumigation**: no lockout at creation; lockout applies at the next posture recompute after the clock passes `application_start` (PRD 3.3's explicit deferred-lockout sentence).
4. **CONTRACT_AVG empty pool**: the shape rule "spot_price forbidden under CONTRACT_AVG" is enforced unconditionally, so an empty-pool CONTRACT_AVG approve always fails `ERR_VALIDATION` (the fallback requires the very input the shape rule forbids — net effect 400 either way; the scaffold's "spot_price iff SPOT clause" supports this).
5. **Claim on OPEN alert**: `closed_at` is null, so the loss-period check (23) cannot bind; the alert-status check (27) reports `ERR_ALERT_LOSS_NOT_CONFIRMED` — the semantically named error for that case.
6. **Fumigation create auth**: present-but-different `applicator_id` → 403 at priority 3 (masks even 404s); a missing `applicator_id` → 400 shape error.
7. **OCC field**: missing or non-integer `expected_contract_version` → 400; present integer mismatch → 412, and the 412 masks other payload defects (verified).
8. **Pre-delivery computed fields** (`scale_tickets`, `gross_bu`, `settled_net_bu`, money fields, `delivered_at`) serialize as null until set; `draws` starts `[]`; `version` starts at 1; the three event-log entities omit `updated_at`/`version`.
9. **Void while gated**: balances reconcile but lots stay `SUSPENDED` (bin still gated); DEPLETED lots revive per the state machine otherwise.
10. **List behavior**: invalid enum filter → 400; FK filters never 404; sort `created_at` ASC with insertion-order tie-break (waterfall: fill_date ASC, created_at ASC, insertion — never id); `lots_assessed` counts every eligible lot processed even if its rounded charge/loss is 0.

Verified with ~110 smoke assertions across 6 suites (auth/RBAC, shrink math, risk score + out-of-order readings, hotspot alerts, posture gate/release cascades incl. permit voiding, fumigation SoD/REI/double-booking/cert, permit SoD/atmosphere, OCC, window containment/overlap, tiered fee boundaries at exactly 200000/500000, 98% fulfillment exactness + revert, atomic waterfall rejection, assessment tallies + sweeps, SPOT/CONTRACT_AVG indemnity with cap-before-deductible, carry CASH/ECONOMIC, pagination) — all pass, and the server boots cleanly via `bash start.sh` with an empty store.

## Step 7: Test-Fix Diagnostic Loop — 2026-08-14T17:20:00.000Z

Iteration 1 sweep: 86/94 passed in each of 8 parallel rounds; the same 8 tests failed deterministically in all 8 rounds (no flakiness). Diagnosed per the PRD-first protocol and fixed:

- test_helpers/assertions.py — added `assert_instant_equal` (instant-value comparison; PRD pins the instant of `lockout_until`/`cleared_at`/`cert_expires_at` but pins 3-fractional-digit serialization only for `created_at`/`updated_at`/envelope timestamps, so exact-string assertions over-specified the PRD).
- test_helpers/__init__.py — exported `assert_instant_equal`.
- test_suite/test_06_boundary_precision.py — added missing `validate_success` import (NameError); converted 2 timestamp string-equalities to `assert_instant_equal`.
- test_suite/test_07_cross_entity_gates.py — added missing `validate_success` import (NameError in 2 tests).
- test_suite/test_10_corner_entities.py — `cert_expires_at` readback now instant-compared.
- test_suite/test_11_corner_state_machines.py — `lockout_until` now instant-compared.
- test_suite/test_03_non_linear_state_machines.py — fixed arithmetically wrong lot expectations in `test_void_reverts_fulfilled_to_delivering_then_second_settle_refills`: void restores the lot to 1000.00 per PRD ("each recorded draw is reversed"), so the second 980.00 settle leaves 20.00/PARTIALLY_DRAWN (was asserted 0.00/DEPLETED).
- workspace/implementation/routes/insurance.py (`approve_claim`) — CONTRACT_AVG shape rule now honors PRD 3.8's empty-pool carve-out ("when the pool is empty the clause falls back to SPOT behavior and the spot price input is then required"): pool emptiness is computed before the conditional spot-price shape check; empty pool -> spot required and valued as SPOT; non-empty pool -> spot forbidden, weighted average used (unchanged).

Iteration 2 verification sweep: **94/94 passed in all 8 parallel rounds — clean.**

## Step 7: Run Tests and Iterate — 2026-08-14T17:05:00.000Z

## Summary

**Exit condition met: all 8 parallel rounds passed 94/94 (zero failures, zero errors) on the verification sweep.**

**Iterations run:** 2 (iteration 1: 86/94 in each of 8 rounds, same 8 tests failing deterministically in every round; iteration 2: clean 94/94 × 8).

**Tests deleted:** none. Every failing test traced to a verbatim PRD rule; no PRD-silence or unique-derivability deletions were warranted.

**Fixes applied to `test_helpers/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1770_farm_grain_storage_bin_management/test_helpers/assertions.py` — added `assert_instant_equal(actual, expected)`: compares ISO 8601 timestamps by instant value. PRD §3.3/§3.1 pin the *instant* of `lockout_until`/`cleared_at`/`cert_expires_at`, but the 3-fractional-digit serialization rule (§2.5/§2.2) covers only `created_at`/`updated_at`/`api_request_timestamp` — so exact-string assertions on those fields over-specified the PRD (STEP 1c partial coverage: kept the covered instant assertion, dropped the uncovered string form).
- `/home/ubuntu/github/CodingPRD/tasks/task_1770_farm_grain_storage_bin_management/test_helpers/__init__.py` — exported `assert_instant_equal`.

**Fixes applied to `test_suite/`:**
- `test_06_boundary_precision.py` — added missing `validate_success` import (NameError in `test_phosphine_clear_at_exactly_rei_succeeds`); converted `lockout_until` and `cleared_at` string-equalities to `assert_instant_equal`.
- `test_07_cross_entity_gates.py` — added missing `validate_success` import (NameError in `test_permit_approve_succeeds_after_fumigation_cleared`, `test_claim_against_confirmed_loss_alert_accepted`).
- `test_10_corner_entities.py` — `test_applicator_create_and_readback`: `cert_expires_at` readback now instant-compared.
- `test_11_corner_state_machines.py` — `test_fumigation_clear_twice_rejected`: `lockout_until` now instant-compared.
- `test_03_non_linear_state_machines.py` — `test_void_reverts_fulfilled_to_delivering_then_second_settle_refills`: the expected lot end-state was arithmetically inconsistent with the test's own scenario under PRD math — PRD §3.6's void reversal ("each recorded draw is reversed — the lot's `current_bu` is credited back") restores the lot to 1000.00, so the second 980.00-bu settle leaves 20.00/PARTIALLY_DRAWN (was wrongly asserted as 0.00/DEPLETED). Assertions and docstring corrected.

**Fixes applied to `implementation/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1770_farm_grain_storage_bin_management/workspace/implementation/routes/insurance.py` (`approve_claim`) — the CONTRACT_AVG spot-price shape rule was enforced unconditionally, which rendered PRD §3.8's empty-pool carve-out ("when the pool is empty the clause falls back to `SPOT` behavior and the spot price input is then required") dead text: empty-pool approvals could never succeed. Now the valuation pool is computed before the shape check; empty pool → spot price required and valued as SPOT; non-empty pool → spot price forbidden and the contracted-bushel-weighted average used (unchanged). Shape-before-state precedence preserved.

## Step 8: Finalize PRD — 2026-08-14T17:15:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1770_farm_grain_storage_bin_management/workspace/PRD_FINALIZED.md` written (copy of PRD.md plus two inline revisions).

## Summary

**Line counts / delta:** PRD.md 284 lines (51,226 bytes); PRD_FINALIZED.md 284 lines (51,877 bytes). Line delta 0.0%; byte delta +651 (+1.27%). Both edits are in-place sentence revisions — no sections added.

**Changes:**
- §2.5 — **revise** — the ISO 8601 UTC three-fractional-digit serialization rule, previously pinned only for `created_at`/`updated_at` (§2.5) and `api_request_timestamp` (§2.2), now explicitly covers every server-emitted timestamp (echoed inputs like `fill_date`/`cert_expires_at`/`application_start`/window bounds, and derived instants like `lockout_until`/`cleared_at`/`closed_at`/`delivered_at`/`last_reading_at`/`current_utc`) — `workspace/implementation/clock.py:25-30` (`format_iso`), `workspace/implementation/services/core.py:87-88` (`iso()`), `workspace/implementation/response.py:21`, `workspace/implementation/routes/clock.py:27`.
- §3.8 — **revise** — the claim-approval conditional-input rule no longer states the blanket "under `CONTRACT_AVG` it must not"; it now carries the empty-pool exception ("except when the valuation pool defined below is empty — the fallback case in which the clause behaves as `SPOT` and the spot price input is then required"), reconciling the shape rule with the section's own fallback sentence and with the fixed implementation — `workspace/implementation/routes/insurance.py:132-154`.

**Step-7 items judged non-PRD (no edit):** the `validate_success` import fixes (test_06, test_07) are pure fixture bugs; the test_03 end-state correction was the test's own arithmetic error — PRD §3.6's void-reversal text already pins 1000.00-restore → 980.00-redraw → 20.00/`PARTIALLY_DRAWN`, and `routes/loadouts.py:320-362` matches it; the `insurance.py` impl fix aligned code to PRD §3.8's existing fallback sentence, so only the contradictory shape-rule sentence needed revision (edit 2).

**Per-edit pre-edit search log:**
1. **§2.5 timestamp serialization** — (a) subject: serialization form of every emitted timestamp. (b) enumerated paths: grepped `isoformat|strftime|format_iso|now_iso` across all of `implementation/` — the only formatter is `format_iso` (clock.py:25-30, always 3 fractional digits + `Z`, UTC-normalized); it feeds `created_at`/`updated_at` (core.py:105/112/116), `api_request_timestamp` (response.py:21), `current_utc` (routes/clock.py:27), and `core.iso()` (core.py:87-88) used by every view for `last_reading_at`, `fill_date`, `recorded_at`, `closed_at`, `application_start/end`, `lockout_until`, `cleared_at`, `planned_start/end`, `window_start/end`, `early_cutoff`, `scheduled_start/end`, `delivered_at`, `cert_expires_at`, `period_start/end` (core.py:356-547). No datetime is emitted by any other path; `period` ("YYYY-MM") is a plain string, not a timestamp. (c) wording adjustment: phrased as "every other timestamp the server emits" with non-exclusive example lists, deliberately avoiding the word "period" alone so the `YYYY-MM` period string is not swept in.
2. **§3.8 claim-approval shape rule** — (a) subject: when `spot_price_cents_per_bu` is required/forbidden at claim approval. (b) enumerated paths: grepped `spot_price|valuation` across `implementation/` — the only consumer is `approve_claim` (insurance.py:119-181): pool computed after claim existence (lines 132-138); `use_spot` = SPOT clause OR (CONTRACT_AVG with empty pool) (139-141); spot required iff `use_spot`, forbidden iff CONTRACT_AVG with non-empty pool (145-154); shape check precedes the `ERR_CLAIM_NOT_SUBMITTED` state check (155-157); valuation follows the same branch (159-166). `create_policy` (insurance.py:18-49) and `policy_view`/`claim_view` (core.py:533-563) touch only the clause enum and serialization, unaffected. (c) wording adjustment: scoped the exception as "when the valuation pool defined below is empty" and left the later pool/fallback sentence verbatim, preserving the shape-before-state precedence claim and consistency with all three branches above.

## Step 9: Complete PRD — 2026-08-14T17:35:00.000Z

All changes verified. The diff shows 24 modified lines (all inline edits — no lines added or removed; both files are 284 lines). Final summary:

## Summary

**Files:** `/home/ubuntu/github/CodingPRD/tasks/task_1770_farm_grain_storage_bin_management/workspace/PRD_FINALIZED.md` (284 lines, 51,877 chars) → `/home/ubuntu/github/CodingPRD/tasks/task_1770_farm_grain_storage_bin_management/workspace/PRD_COMPLETED.md` (284 lines, 55,187 chars; **+3,310 chars, +0 lines** — all changes are inline in-paragraph inserts/revisions).

**Counts:** 31 changes total — **30 ambiguity-pins, 1 mismatch-revision** (24 insert, 7 revise; one revise is the mismatch).

**Changes:**

- §2.1 — insert — ambiguity — empty header value counts as missing for the 401 check — implementation/middleware.py:16-20
- §2.2 — insert — ambiguity — `api_request_timestamp` is stamped from the logical clock, never wall-clock — implementation/response.py:18-22
- §2.2 — insert — ambiguity — unrouted paths and unsupported methods answered with `ERR_NOT_FOUND` (404) in the same envelope — implementation/app.py:33-39
- §2.3 — insert — ambiguity — non-integer `limit`/`offset`, limit outside 1–100, negative offset → `ERR_VALIDATION` (400) — implementation/util.py:132-154
- §2.3 — insert — ambiguity — `created_at` sort ties break by server acceptance (insertion) order — implementation/util.py:157-165
- §2.3 — insert — ambiguity — invalid enum filter value → `ERR_VALIDATION`; identifier filters are equality-only (nonexistent id yields empty page, not 404) — implementation/util.py:168-180
- §2.4 — insert — ambiguity — clock may be set to any instant (no monotonicity constraint); missing/unparseable `to_iso8601` → `ERR_VALIDATION` — implementation/routes/clock.py:14-27, clock.py:43-45
- §2.5 — insert — ambiguity — `created_at`/`updated_at` stamped from the logical clock — implementation/services/core.py:103-112
- §2.5 — insert — ambiguity — client timestamps may carry any ISO 8601 offset (normalized to UTC); offset-less values read as UTC — implementation/clock.py:9-22
- §2.5 — insert — ambiguity — `version` starts at 1 at creation — implementation/services/core.py:103-107
- §2.6 — insert — ambiguity — temperature inputs taken at 1 decimal place; per-cable temperature entries carry no range restriction — implementation/routes/readings.py:28-38
- §2.6 — insert — ambiguity — quantities/scores/ratios serialize as JSON numbers; monetary cents as JSON integers — implementation/services/core.py:75-84
- §2.8 — insert — ambiguity — non-integer `expected_contract_version` is a shape defect (`ERR_VALIDATION`); the stale comparison applies only to integers — implementation/routes/loadouts.py:43-48, 60-63
- §2.9 — insert — ambiguity — body FKs resolve in the order the endpoint narrative names them; absent/null FK field is a shape defect, only present-but-unresolvable values yield `ERR_NOT_FOUND` — implementation/util.py:118-129
- §2.9 — insert — ambiguity — a request body that is not a JSON object is a shape defect — implementation/util.py:26-35
- §3.2 — insert — ambiguity — two readings with identical `recorded_at` resolve to the one the server accepted later — implementation/services/core.py:215
- §3.3 — insert — ambiguity — applicator-acts-as-self equality applies to a present `applicator_id`; an absent one is `ERR_VALIDATION` — implementation/routes/fumigations.py:26-28, 34
- §3.3 — insert — ambiguity — clearance checks only the X-User-ID inequality; the clearing caller is not resolved against registered applicators — implementation/routes/fumigations.py:107-109
- §3.4 — revise — **mismatch** — permit voiding pinned to the bin's posture entering `FUMIGATION_LOCKOUT` (immediate when `application_start` ≤ now at creation, otherwise at the first recompute after the clock reaches it), not to bare fumigation creation — implementation/services/core.py:253-268, 309-311; routes/fumigations.py:68-70
- §3.6 — insert — ambiguity — `ticket_no` may be a string or an integer — implementation/routes/loadouts.py:197-199
- §3.6 — insert — ambiguity — delivery shape rules fire before the `DISPATCHED` state check (per §2.9) — implementation/routes/loadouts.py:184-213
- §3.6 — insert — ambiguity — allocation waterfall: lots sharing both `fill_date` and `created_at` break the tie by server acceptance order — implementation/routes/loadouts.py:260
- §3.6 — insert — ambiguity — `draws` entries carry `lot_id` and `bu` keys — implementation/routes/loadouts.py:294, 513
- §3.6 — insert — ambiguity — a lot revived by voiding while its bin is gated (`ALERT`/`FUMIGATION_LOCKOUT`) becomes `SUSPENDED` instead of `STORED`/`PARTIALLY_DRAWN` — implementation/routes/loadouts.py:329-348
- §3.6 — insert — ambiguity — the load-out's `draws` array and settlement money fields are retained after voiding as audit — implementation/routes/loadouts.py:320-362
- §3.7 — insert — ambiguity — malformed `period` string → `ERR_VALIDATION` (400) before the uniqueness check — implementation/routes/assessments.py:22-30
- §3.7 — insert — ambiguity — eligible lots are processed in creation order (`created_at` ascending) — implementation/services/core.py:607
- §3.7 — revise — ambiguity — `lots_assessed` counts every eligible lot processed (charge may round to zero cents) — implementation/services/core.py:608-633
- §3.7 — revise — ambiguity — the epoch recomputes the posture of every bin (inventory recomputed only for bins whose lots moved) — implementation/services/core.py:676-683
- §3.8 — insert — ambiguity — a never-closed alert has no `closed_at`, so the coverage-period check does not bind and the `CONFIRMED_LOSS` requirement reports it — implementation/routes/insurance.py:62-77
- §3.9 — revise — ambiguity — `current_basis_cents` and `variant` are required query parameters; missing/non-integer/out-of-enum → `ERR_VALIDATION` (400) — implementation/routes/lots.py:130-131, 159-165; util.py:183-190

Everything else in the implementation — endpoint inventory and roles (§4), error catalogue (§5), the posture ladder and cascade matrix (§2.7), OCC ordering (§2.8), per-endpoint guard chains (§3.1–§3.8), shrink/fee/indemnity/carry formulas, REI hours, fulfillment threshold semantics, and all serializer field shapes — was already uniquely pinned by PRD_FINALIZED.md and matched the code exactly, so it was left untouched.
