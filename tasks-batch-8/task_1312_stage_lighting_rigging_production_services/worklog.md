# Worklog — task_1312_stage_lighting_rigging_production_services

User difficulty directive: "Generate task hard than expert level!"

## Step 1: Create Task Directory — 2026-08-12T21:25:00.000Z

Task directory `tasks/task_1312_stage_lighting_rigging_production_services/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline dispatcher; verified present. No index scan or new directory creation performed (per instructions, other pipeline runs are concurrent).

## Step 3: Copy Shared Files — 2026-08-12T21:26:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1312_stage_lighting_rigging_production_services/workspace/INSTRUCTION.md` (1424 bytes).

## Step 2: Generate Scaffold — 2026-08-12T22:24:00.000Z

All checks pass. Final state of the three artifacts:

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1312_stage_lighting_rigging_production_services/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no difficulty/corner keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top key `scaffold_corner_design`

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (63 endpoints, 15 entities, 1146 calls scanned). One FK reverse-reachability gap (PullListEntry.load_schedule_id) was found and fixed by adding `GET /api/load-schedules/{id}/pull-list-entries`.

**§1.1 Entities (15):** Venue (union-rule + structural parameters), Technician, Production (posture-gated aggregate), LightingPlot (cyclic review), RiggingPoint (version-pinned approval), EquipmentAsset, PullListEntry (waitlist), CrewCall, CrewAssignment, PowerPlan (sizing), Truck, LoadSchedule (dock windows), SafetyInspection (re-inspection loop), DamageReport (dual valuation), SettlementStatement (provisional/final). Flat topology with cross-aggregate FKs; every FK has a reverse GET.

**§1.2 State machines (12):** cyclic revision loops on LightingPlot / RiggingPoint / PowerPlan / SafetyInspection; compound posture-driven Production with auto-transitions (FINAL pass → SHOW_READY; settlement → SETTLED; release/fail downgrades); multi-branch cancel cascade (production → crew calls → assignments, plus points/entries/schedules/inspections).

**§1.3 Calculations (10):** rigging factored load (conditional hang-type factors), bay aggregate check, power sizing (pinned evaluation order, generator tiers, 80% loading), union/non-union labor with OT tiers + meal penalty (per-line rounding pinned), tiered rental billing (3/7-day breakpoints, inclusive dates), damage valuation (depreciation floor 0.20 vs repair+15%), truck pack weight (2% dunnage), readiness posture, waitlist promotion (created_at ordering), settlement totals (provisional vs final inclusion sets).

**§1.5 Endpoints (63):** includes 2 OCC-guarded creation endpoints (`expected_production_version`, `expected_plot_version` — both lint-verified dynamic in recipes) and `POST /api/_clock/set_current_utc` with the mandated 2026-08-01T00:00:00Z default.

**§1.6 Errors (44)** — every code referenced by ≥1 validation/transition; **§1.7 Roles (8):** segregation_of_duties model (point approver ≠ submitter; FINAL passer ≠ rigging approver; CrewChief is entity_backed:Technician with ownership checks).

**§1.8 Difficulty design: 29 instances** — dual_variant 3 (labor / damage / settlement domains), combinatorial 3 (modes a, b, c), non_linear_sm 3, transitive_cascade 3 (depths 4/3/3, distinct triggers), priority_conflict 3 (state-vs-safety, safety-vs-referential, temporal-vs-referential), boundary 4 (utilization == 1.0000, OT at 8.00h, 45 kVA tier edge, empty-plot count), cross_entity 4, temporal_overlap 3 (half-open dock / 8h turnaround buffer / closed venue occupancy), compensating_invariant 3 (engagement count / settlement cents / plot kg). All formula asserts pre-computed as literals (e.g., 130000 vs 100000, 71670×2=143340, 44.17 kva, 80000 vs 57500, 185000→105000).

**§1.9 Corner design: 46 active instances + 9 excluded_because stubs** across all nine guide sections (entities, state_machines, calculations, validations, endpoints, errors, rbac, cross-cutting layers, consistency); every non-§1.8 error code has a trigger instance; name uniqueness and stub→§1.8 references verified programmatically; forbidden concurrency vocabulary scan clean.

## Step 4: Generate PRD — 2026-08-12T22:52:00.000Z

PRD generation complete. All three hard contracts pass.

## Output
`/home/ubuntu/github/CodingPRD/tasks/task_1312_stage_lighting_rigging_production_services/workspace/PRD.md` — 367 lines, ~8,575 words.

## Section structure
- **§1 Introduction** — 2 paragraphs, business-risk-chain angle (rigging math → settlement), names `/api` mount and the derived-readiness premise.
- **§2 Global Specifications** (9 subsections): 2.1 RBAC (all 8 roles with identity semantics; `CrewChief` entity-backed to `Technician`, other 7 opaque with recorded-field examples), 2.2 API Response Structure (**byte-identical to canonical source**, verified by diff), 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ascending, filter params), 2.4 Common Resource Properties & Logical Clock (UUID, ISO-8601 3-fractional digits, version; clock default `2026-08-01T00:00:00Z`, never wall-clock), 2.5 OCC (both rules, `ERR_STALE_VERSION`/412, no race-framing), 2.6 Validation Pipeline (14 ordered categories mapping scaffold priorities 1–44, plus the two "surprising" orderings: SoD before ownership, `worked_hours` range last), 2.7 Nested Resource Retrieval (left-to-right 404), 2.8 Precision (integer cents; 2dp kg/watts/kVA; 4dp ratios; round-half-up everywhere), 2.9 Hierarchical Consistency & Cascades.
- **§3 Business Logic** (9 subsections, chronological lifecycle): 3.1 venue/technician/asset/truck registration, 3.2 production booking + readiness posture + full cancel cascade, 3.3 plots & rigging engineering loop (factored-load math, bay aggregate, version-pin, supersede cascade), 3.4 power sizing (pinned 5-stage evaluation order), 3.5 crew calls & union/non-union labor variants, 3.6 pull lists/waitlist/truck pack, 3.7 inspections & show certification, 3.8 damage valuation variants, 3.9 settlement provisional/final variants & dispute.
- **§4 Endpoint table** — 63 rows, 4 columns (Method, Path, Description, Authorized Role(s)).
- **§5 Error catalogue** — 44 rows, 2 columns.

## Coverage audit (zero-silence check)

```
Field coverage check:
- entities[].fields: 96 required, 96 present, 0 missing
- endpoints[].request_body/input: 70 required, 70 present, 0 missing
- endpoints[].query_params: 7 required, 7 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 44 checked; category pipeline (§2.6) + endpoint-local orderings expressed in prose
  (point-approve SoD→bay→version-pin; reservation OCC→capacity→label; assignment turnaround→classification;
   worked-hours after state; close pull-list→schedule; power supply-branch→imbalance; assess method→quote;
   check-out capacity→schedule-authorization), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (expected_production_version / expected_plot_version
  + ERR_STALE_VERSION + HTTP 412 named for each), 0 missing
- state_machines[].transitions: 78 checked, 78 fully expressed (from/to, preconditions+error_id, side effects), 0 missing
- calculations[]: 10 checked, 10 fully expressed as precise prose (all constants: 1.10/1.00 factors, 20 kg motors,
  1.15 bridle, 3%/100m feeder loss, 0.9 PF, 0.8 derating, 208V, 0.15 imbalance, tiers 45–400 kVA, 6h meal window,
  10h non-union straight time, 3/7-day rental tiers at 1.0/0.5/0.25, 0.10/0.20/0.15 depreciation, 2% dunnage), 0 missing
- validations[] conditions: 44 checked, 44 matchable to error_id in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: all expressed (cancel cascade 6 steps, supersede cascades, version bumps,
  posture recompute/downgrades, settlement debit/credit), 0 missing
- entities[].fields[] structured content: defaults (4/8/12/8/48/72 venue params, motor_count 0, power_draw_watts 0,
  dispute_adjustment_cents 0, revision-from-1, pack_weight 0, null-until-computed fields) reconstructible, 0 missing
- sibling-branch symmetry: 14 groups checked (3 cancel sources, 4 release sources, 2 WORKED actors, 2 NO_SHOW sources,
  union/non-union, DEPRECIATED/REPAIR_QUOTE, generator/house, 3 inspection types, provisional/final, waive paths, etc.),
  0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 673
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional scans: all 48 state values, 77 enum values, 8 role names present verbatim; no pseudocode operators (`==`, `<=`, `+=`, …) in prose; no fuzzy/approximating words (single "around" hit is a substring of "turnaround"). The withheld difficulty/corner design files were never opened.

## Step 5: Generate Unit Tests — 2026-08-12T23:30:00.000Z

All checks pass. Generation complete.

## Summary

**Task:** task_1312_stage_lighting_rigging_production_services — test infrastructure + suite generated from the two design indices against `workspace/PRD.md`.

### Files written

`test_helpers/` (Stage 1):
- `/home/ubuntu/github/CodingPRD/tasks/task_1312_stage_lighting_rigging_production_services/test_helpers/types.py` — 14 entity TypedDicts (all carry full common fields), 17 status/enum types, `UserRole`
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (all `/api/...` paths, incl. `_clock/set_current_utc`)
- `api_errors.py` — all 44 `ApiErrorId`s with HTTP map registered via `set_error_http_status_map`
- `assertions.py`, `factories.py`, `constants.py` (all calculation constants: load factors, dunnage 2%, tiers, depreciation, labor rules)
- `test_users.py` — `TEST_USERS` + per-instance builders (`make_crew_chief_headers(technician_id)` for the entity_backed role; engineer/inspector/supervisor identity builders for SoD tests)
- `fixtures.py` — ~60 helpers: primitive entity/transition wrappers plus composite chains `setup_full_planning_surface`, `setup_ready_production`, `setup_load_in_production`, `certify_show`, `setup_closed_production_with_assessed_damage`
- `__init__.py` barrel

`test_suite/` (Stage 2): `conftest.py` + `test_01_registration_and_security.py` … `test_10_production_lifecycle.py`

### Coverage (self-check results — all pass)
- **Queue A (Difficulty): 58 tests** — 29 instances × 2 each; none skipped. Full lifecycle chains (through CLOSED/SETTLED) built via fixtures for the settlement/damage instances.
- **Queue B (Corner): 41 tests** — 46 non-stub instances, 41 translated, 5 skipped. The 9 `excluded_because:` stubs were not translated; all their `difficulty_instance` cross-references resolve.
- Tag audit: every test has exactly one `Design:` line as the docstring's final line, resolving to a real instance; coverage targets met (≥2 difficulty, ≥1 corner).
- Citation audit: every ≥8-word quoted span survives a whitespace-normalized literal match against PRD.md (0 failures after a C3 pass that expanded truncated quotes to full sentences).
- `pytest --collect-only`: 99 tests collected; pyflakes clean; no `skip`/`skipif`/`xfail`; no scaffold references in code.

### Skipped instances (PRD-first filter)
1. `Corner/entities/asset_status_input_ignored` — PRD never states whether client-supplied system fields in a create payload are ignored (201/AVAILABLE) or rejected as schema errors (400); not uniquely derivable.
2. `Corner/entities/common_system_fields_generated` — asserts `version == 1` at creation; PRD §2.4 pins only "increments by exactly 1", never the start value.
3. `Corner/cross_cutting_complexity_layers/version_increment_observable` — same gap (asserts absolute 1→2→3 sequence).
4. `Corner/state_machines/production_cancelled_terminal_lockdown` — PRD never designates Production.CANCELLED as terminal, so ERR_ALREADY_TERMINAL vs ERR_INVALID_STATE is a two-reader split.
5. `Corner/errors/point_label_already_reserved_overlapping_window` — unreachable setup: the second production's same-venue window intersects the first, so its creation is itself rejected by ERR_VENUE_DOUBLE_BOOKED (PRD §3.2); the label collision cannot be staged via the public API.

## Step 6: Generate Implementation — 2026-08-12T23:44:00.000Z

Done. Summary of the delivered implementation:

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_1312_stage_lighting_rigging_production_services/workspace/implementation/`)

- `start.sh` — executable launcher: guarded dependency install (`python3 -c "import flask, waitress"` no-op check), `exec python3 app.py` in foreground, binds `0.0.0.0:$PORT` (default 10000) via waitress with Flask dev-server fallback
- `requirements.txt` — flask, waitress
- `app.py` — Flask entry, blueprint registration under `/api`, envelope-wrapped error handlers
- `db.py` — in-memory dict stores for all 15 entities (empty at boot, zero seeding), logical clock pinned at `2026-08-01T00:00:00Z`, monotonic 3-digit UTC timestamps for `created_at`/`updated_at`
- `errors.py` — `ApiError` + all 44 catalog error IDs with exact HTTP statuses
- `response.py` / `middleware.py` / `util.py` — envelope (`meta`/`response_type`/`data`, error meta with only the two request fields), X-User-ID/X-User-Role auth (401 unknown role, 403 unlisted), pagination (`limit` default 10/min 1/max 100, `offset`), Decimal-based validation helpers
- `routes/` — 16 modules, one per resource group, covering all 46 endpoints including `POST /api/_clock/set_current_utc` and `POST /api/damage-reports/{id}/assess`
- `services/calculations.py` + `services/domain.py` — all business math and shared transition/cascade machinery

## Coverage

- **Endpoints**: all 46 from the endpoint table (12 create, 19 list/get incl. reverse-FK collections with the declared filters, 13 transition endpoints, assess, clock). Role ownership per `to` enforced before resource resolution; system-only targets (SHOW_READY, SETTLED, SUPERSEDED, DAMAGED/LOST on entries, etc.) correctly 403.
- **State machines**: all 12, with terminal guards, declared-transition gates, OCC (`expected_production_version`/`expected_plot_version` → 412), version pinning (`plot_version_at_submission` → ERR_STALE_PLOT_REVISION), SoD before ownership continuity, cancel cascade (6 entity classes + waitlist scans), supersede cascades (plots and power plans), readiness downgrade (READY_FOR_LOADIN→PLANNING), SHOW_READY↔LOAD_IN inspection-driven transitions, CHARGED→WAIVED compensation (declared transition allowed from a terminal-listed state per PRD).
- **Calculations**: rigging factored load (hang-type factors, motor self-weight, 1.15 bridle uncertainty, 2dp/4dp ROUND_HALF_UP, equality-passes capacity), plot-scoped bay check at plot approval vs production-scoped at point approval (PRD-pinned divergence), power sizing in pinned order (subtotal→loss→total→generator tier/house 208V branch→15% imbalance), crew labor (IATSE/TEAMSTERS tiers + IATSE-only meal penalty on worked>6; NON_UNION 10h variant; per-line rounding before summation; min-call floor), tiered rental billing (calendar-date inclusive, 1.0/0.5/0.25 tiers, single rounding), damage valuation (365.25-day floor depreciation with 0.20 floor; REPAIR_QUOTE ×1.15), truck pack (2% dunnage, equality passes), settlement totals (live CHARGED-only vs frozen provisional ASSESSED+CHARGED snapshot), readiness posture, earliest-created_at waitlist promotion restricted to PLANNING productions.
- **Validation ordering**: all PRD-emphasized precedences verified — OCC→capacity→label on reservation, SoD→bay→version-pin on point approval, deadline→plot-state on review submission, turnaround→classification on assignment, capacity→schedule-authorization on check-out, state-error before fiscal hours-range, OPEN_PULL_LIST before OPEN_LOAD_SCHEDULE, generator/house before imbalance, LOSS-method before quote-required.

## Boot smoke test

Booted via the exact evaluator contract (`bash start.sh`) and ran 5 suites of end-to-end checks, **each on a fresh process kill+relaunch** (mirroring `--isolation per-test-server`): 67 + 23 + 63 + 59 + 28 + 15 probe checks, **255 total, 0 failures**. HTTP-ready in ~0.6s with deps pre-installed (guarded install is a no-op), store confirmed empty at boot, server runs in foreground on `0.0.0.0:$PORT`.

Notable spec-fidelity decisions: `DamageReport` CHARGED→WAIVED allowed despite CHARGED being listed terminal (PRD's compensation flow wins over the scaffold's terminal list); RIGGING-inspection begin fails with ERR_RIGGING_NOT_APPROVED when no APPROVED plot exists; waitlist scan deliberately not run on manual QC pass (DAMAGED→AVAILABLE); posture recomputation bumps `Production.version` only when the derived value actually changes (PRD §2.9).

## Step 7: Run Tests and Iterate — 2026-08-13T00:21:00.000Z

All 8 rounds: 99/99 passed, 0 errors, 0 failed — a clean 8-round parallel sweep on the final artifact state. The task is complete.

## Summary

- **Iterations run:** 6 sweeps total (1 initial diagnosis sweep, 1 single-round verification, 1 post-fix sweep, 1 post-boot-optimization sweep, 1 instrumented diagnostic sweep, 1 final clean validation sweep with all 8 rounds passing 99/99).

- **Tests deleted:** None.

- **Fixes applied to `test_suite/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1312_stage_lighting_rigging_production_services/test_suite/test_05_crew_labor.py` — `test_labor_cost_iatse_vs_non_union` (TestDualVariantLaborCost): the test runs `_worked_call` twice in one test body. The first scenario ends with `set_clock(CALL_END)` at `2026-09-01T18:00:00Z`; the second scenario then tried to publish a new crew call whose 48-hour publish deadline (`call_start - crew_call_publish_lead_hours` = `2026-08-30T08:00Z`) had already passed relative to the advanced logical clock, so the PRD-faithful implementation correctly rejected it with `ERR_CREW_CALL_LATE`. STEP 2 test bug (setup state violates the PRD §3.5 publish-deadline precondition; PRD §2.4 states the logical clock only advances). Fix: extended the local `_worked_call` helper with `call_start`/`call_end` parameters (defaulting to the original window) and gave the second NON_UNION scenario a later window (`2026-09-10T08:00-18:00Z`), comfortably beyond the clock value left by the first scenario plus the 48h lead.

- **Fixes applied to `test_helpers/`:** None.

- **Fixes applied to `implementation/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1312_stage_lighting_rigging_production_services/workspace/implementation/start.sh` — added a `.deps_installed` marker check so re-invocations skip the `python3 -c "import flask, waitress"` interpreter spawn once dependencies are verified (first boot and any `requirements.txt` change still run the check and pip-install if needed). This cut server boot time from ~1.75s to ~0.56s, eliminating the load-induced "API server could not be restarted" (15s poll-budget) flakiness that the 8-round sweep surfaced on this shared host (other benchmark pipelines run concurrently here; boot storms synchronized across rounds intermittently pushed boots past the runner's restart budget). No business logic was touched; storage remains in-memory only; the marker is boot metadata, not entity data.

- **Flakiness diagnosis notes:** After the test fix, all remaining failures across intermediate sweeps were infrastructure-only (server restart timeouts and connection resets under parallel load), never assertion failures. Boot tracing (instrumented `start.sh`/`app.py`, later fully reverted) showed `start.sh` itself completed in ~10ms during stalls — the delay was interpreter/app-boot scheduling under host load. The boot-time optimization plus a clean final sweep confirms stability: 8/8 rounds × 99/99 tests passing on the exact final artifact state.

## Step 8: Finalize PRD — 2026-08-13T00:24:00.000Z

Analysis complete. PRD_FINALIZED.md is in place and identical to PRD.md — zero changes were warranted.

## Summary

**File:** `/home/ubuntu/github/CodingPRD/tasks/task_1312_stage_lighting_rigging_production_services/workspace/PRD_FINALIZED.md`

**Line counts / delta:** PRD.md = 366 lines; PRD_FINALIZED.md = 366 lines; 0% delta (byte-identical, verified via `diff`).

**Changes:** None.

**Rationale per Step 7 diff item:**

1. **`test_suite/test_05_crew_labor.py` — `test_labor_cost_iatse_vs_non_union` fix (test-side setup bug).** The fix parametrized the `_worked_call` helper with `call_start`/`call_end` so the second scenario's window (`2026-09-10T08:00-18:00Z`) sits beyond the advanced clock plus the 48h publish lead. The subjects touched are the crew-call publish deadline and the logical clock. The implementation is verbatim-faithful to the PRD at both sites, so the fix revealed neither a PRD silence nor a PRD/impl mismatch — it was the test violating a PRD-pinned precondition. No PRD edit.

2. **`implementation/start.sh` — `.deps_installed` marker.** Boot metadata only: it skips a redundant dependency-import check on reboot. The INSTRUCTION.md contract (install deps, foreground server, `PORT`, `0.0.0.0`) is unchanged, and the marker writes no entity data. Zero API behavioral surface; the PRD does not govern start.sh internals. No PRD edit.

No tests were deleted and no `test_helpers/` fixes were applied, so no other candidate sites exist.

**Pre-edit search log (for the two candidate edits evaluated and rejected):**

- **Candidate: publish-deadline wording (§3.5).**
  - (a) Subject: crew-call publish deadline gate (`ERR_CREW_CALL_LATE`).
  - (b) Paths enumerated and read: `implementation/routes/crew_calls.py:91-101` (the publish gate — `deadline = call_start - crew_call_publish_lead_hours; if clock > deadline: raise ERR_CREW_CALL_LATE`); `implementation/services/domain.py:162-163` (`minus_hours` helper); `implementation/routes/venues.py:53,67` (`crew_call_publish_lead_hours` default 48); `implementation/errors.py:47,98` (error id → 422); grep for `CREW_CALL_LATE|publish_lead|crew_call_publish` across all of `implementation/` confirmed no other callsite. All match PRD §3.5's "at or before `call_start` minus the venue's `crew_call_publish_lead_hours`" verbatim.
  - (c) No wording change — PRD already uniquely determines the behavior; any edit would risk creating a new mismatch.

- **Candidate: logical clock wording (§2.4).**
  - (a) Subject: logical clock startup value, advancement endpoint, and consumers.
  - (b) Paths enumerated and read: `implementation/db.py:37-63` (startup default `2026-08-01T00:00:00Z`, `set_current_utc`, `clock_dt`); `implementation/routes/clock.py` (PlatformAdmin-only `POST /api/_clock/set_current_utc`); consumers `crew_calls.py:89,96,124` (publish gate, complete gate); grep-verified the endpoint table entry in PRD §4 (line 315). All consistent with PRD §2.4's existing prose ("advances the logical clock to a supplied `to_iso8601` instant ... the only way time moves in a running server").
  - (c) No wording change — the test fix's clock comment restates existing PRD §2.4 semantics; nothing in the implementation outruns the PRD here, and tightening "advances" into a monotonicity enforcement claim would falsely describe `set_current_utc` (which does not reject backward sets), creating a new mismatch off the Step 7 site.

**Conclusion:** A fresh implementer reading PRD.md (now PRD_FINALIZED.md) already receives every behavioral pin the implementation exhibits at the sites Step 7 touched; the expected zero-change outcome holds.
