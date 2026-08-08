# Worklog — task_0856_septic_onsite_wastewater

Scenario: 856. Septic & On-Site Wastewater Permit (health dept): site evaluation & perc test, system design & permit, installer license & cover inspection, operating permit & pumping compliance, failure & repair order, well-setback & water-quality, real-estate transfer inspection, reporting

Difficulty: Expert (passed to Step 2 only)

## Step 1: Task directory — pre-assigned (index scan SKIPPED per invocation) — 2026-07-26T06:45:00.000Z

Directory `/home/ubuntu/github/CodingPRD/tasks/task_0856_septic_onsite_wastewater/` with `workspace/` was pre-created and pre-assigned by the caller. No `./tasks/` index scan performed (concurrent pipelines).

## Step 2: Generate scaffold — 2026-07-26T07:41:00.000Z

All three artifacts are generated, parse cleanly under `yaml.safe_load`, and the scaffold linter reports a clean run.

**Lint verdict (verbatim):**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    53
  §1.1 entities declared:     12
  §1.8 instances scanned:     19
  §1.9 instances scanned:     61
  Calls scanned (§1.8+§1.9):  805

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_0856_septic_onsite_wastewater/`): `SCAFFOLD.yaml` (2609 lines), `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1732), `SCAFFOLD_CORNER_DESIGN.yaml` (3668).

**Counts**
- Entities 12 · State machines 11 (across 8 entities, incl. 3 second-dimension machines) · Concurrency rules 2 (OCC on `Parcel.version` and `SiteEvaluation.version`)
- Calculations 19 · Validations 27 (single ordered priority ladder 1→27) · Endpoints 53 · Errors 44 · Roles 7
- §1.8: 9 rule blocks, **19 instances** (dual_variant 2, combinatorial 3, non_linear_sm 2, cascade 2, priority_pair 2, boundary 2, cross_entity 2, temporal_overlap 2, compensating 2)
- §1.9: 9 sections, **68 instances** (61 with full `test_recipe`, 7 `excluded_because` stubs)

**Design notes**
- Profile: `compliance_audit` × `temporal_windowing`, flat topology, cyclic state-machine shape, segregation-of-duties role model, immediate consistency. Layers: OCC, cascading side effects, dual-variant calculation, rate/threshold triggers.
- Rule 1 (dual-variant) sits on two different domains: perc-rate PRELIMINARY-mean vs CERTIFIED-slowest-hole (selects different soil loading tiers → 600 vs 450 sqft) and transfer-certificate DESK_REVIEW vs FIELD_VERIFIED (CONDITIONAL vs SATISFACTORY on identical records).
- Rule 2 spans all three modes: 4-input non-linear drainfield sizing (a), per-line-item rounding on the permit fee — 73018 vs the sum-then-round 73017 (b), and expedite-tier-from-subtotal (c).
- Rule 8 uses two genuinely different interval semantics: contractor calendar = half-open + 45-min *trailing* buffer (exact adjacency legal), parcel construction window = closed interval, unbuffered (endpoint touch conflicts).
- Rule 9 conserves two different quantities across the same compensating action (permit void): money (`fee_balance_cents`) and hydraulic design flow (`permitted_design_flow_gpd`).
- Logical clock endpoint `POST /_clock/set_current_utc` with the mandated `2026-05-01T00:00:00Z` default; it doubles as an ops-run checkpoint (permit/operating-permit expiry, compliance re-derivation).
- A global `DATETIME_RENDERING` constant pins every datetime — including echoed client inputs — to `…T00:00:00.000Z`, and `required_drainfield_area` explicitly mandates exact-decimal arithmetic so `360 / 0.60` ceils to 600 rather than 601.
- All formula-derived assert values were computed in Python before being written as literals (73018, 89031, 89671, 900, 4000, 33600, 36800, 14.33, etc.).

**Orchestrator post-checks**: all 3 files `yaml.safe_load` clean; ALL_CAPS constant sweep found no undeclared constants (`SETBACK_BASE_FT` and `REPAIR_DEADLINE_DAYS` are declared as per-key maps at SCAFFOLD.yaml:1481 and :1625).

## Step 3: Copy shared files — 2026-07-26T07:43:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-07-26T07:55:00.000Z

All three hard contracts pass. The PRD is complete.

**Output:** `workspace/PRD.md` — 447 lines.

**Section list**
- §1 Introduction (3 paragraphs)
- §2 Global Specifications: 2.1 Departmental Actors and Access Control · 2.2 API Response Structure (verbatim fixed block) · 2.3 Pagination and List Ordering · 2.4 Record Identity, Versioning and Timestamp Rendering · 2.5 The Logical Clock · 2.6 The Order in Which a Request Is Refused (full 27-priority ladder) · 2.7 Stale-Read Protection on Cross-Aggregate Writes (OCC) · 2.8 Measurement, Rounding and Money · 2.9 Derived State and Cascade Discipline
- §3 Business Logic: 3.1 The Parcel (allowance/ledgers/risk) · 3.2 Wells, Water Samples and the Groundwater Advisory Cascade · 3.3 Site Evaluation · 3.4 The System Design · 3.5 Licensed Firms and the Construction Permit · 3.6 Field Inspections and the Four-Eyes Rule · 3.7 The Operating Permit (two dimensions) · 3.8 Failures, Repair Orders and Enforcement · 3.9 Transfer Certificates and Departmental Reporting
- §4 Endpoint Definitions (4-column table) · §5 Error Code Catalogue (2-column table)

**Verified coverage**
- **Endpoints: 53/53** rows in the §4 table (verified programmatically; all 5-pipe well-formed)
- Errors: 44/44 rows in §5, and all 44 IDs also mentioned in §2/§3 narrative
- Calculations: 19/19 (all constants embedded in prose — 20 sqft/gpd & 1500 cap, 10.0 mg/L MCL, 5/15/30/60/120 perc tiers → 1.20/0.80/0.60/0.40/0.20, 120 gpd/bedroom & 2-bedroom floor, 1.00/1.25/0.75/0.85 tech multipliers, 36 in / 1.20 shallow penalty, 150–4000 clamp, 100/100/75/75 setbacks + 25 sandy surcharge, 45000/65/0-30000-42500-27500/15000 fee lines with the 1.0675 per-line rounding, 45-min travel buffer, 500/300/200/125 tank tiers → 60/48/36/24/12 months, 90-day due-soon, 40/25(cap 2)/20/35 risk points with 25/60 tier gates, 10/30/90 repair deadlines + 30-day/2-max extensions, 18500/9500/4000 + 20000/30000 tiers at 30/20/15 percent)
- Validations: 27/27 in exact priority order with their `error_id`s and full `applies_to` sets
- State machines: 11/11 (incl. both cyclic loops, the parallel OperatingPermit `status` × `compliance_status` pair, and the branching RepairOrder resolve/escalate divergence)
- Entities: 12/12 · Roles: 7/7 with every `identity:` translated · Concurrency rules: 2/2 (`expected_site_evaluation_version`, `expected_parcel_version`, both 412)
- Global constants: all 6 (default clock `2026-05-01T00:00:00Z`, 3-digit `.000Z` datetime rendering, 5-year site-eval validity, 18-in limiting layer, 5-year permit term, 180-day certificate validity)

**Hard contract reports**

```
Field coverage check:
- entities[].fields: 108 required, 108 present, 0 missing
- endpoints[].request_body: 60 required, 60 present, 0 missing
- endpoints[].query_params: 22 required, 22 present, 0 missing
Status: PASS
```
```
Rule coverage check:
- validations[] with priority: 27 checked, 27 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed, 0 missing
- state_machines[].transitions: 11 machines / 62 transitions checked, 62 fully expressed, 0 missing
- calculations[]: 19 checked, 19 fully expressed, 0 missing
- validations[] conditions: 27 checked, 27 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 53 checked, 53 expressed, 0 missing
- entities[].fields[] structured content: 108 checked, 108 reconstructible, 0 missing
- sibling-branch symmetry: 6 groups checked (site-eval APPROVE/REJECT, design APPROVE/REQUEST_REVISIONS, variance GRANT/DENY, permit VOID/EXPIRE, repair REPAIRED/ESCALATE, transfer DESK_REVIEW/FIELD_VERIFIED), 6 equal density, 0 asymmetric
Status: PASS
```
```
Path purity check (§3 only):
- backtick tokens scanned: 898
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, and no sibling task directory was read.

**Orchestrator post-check**: PRD §4 endpoint rows = 53 == SCAFFOLD.yaml endpoints = 53. ✔

## Step 5: Generate unit tests — 2026-07-26T14:05:00.000Z

Test infrastructure and suite are complete and verified.

## Files

**`test_helpers/` — 2,043 lines**

| File | Lines |
|---|---|
| `__init__.py` | 47 |
| `api_client.py` | 269 |
| `api_errors.py` | 102 |
| `assertions.py` | 348 |
| `constants.py` | 111 |
| `factories.py` | 171 |
| `fixtures.py` | 517 |
| `test_users.py` | 75 |
| `types.py` | 403 |

**`test_suite/` — 4,300 lines, 101 tests**

| File | Lines | Tests |
|---|---|---|
| `conftest.py` | 66 | – |
| `test_01_parcels_and_ledgers.py` | 425 | 13 |
| `test_02_wells_and_water_quality.py` | 390 | 9 |
| `test_03_site_evaluations.py` | 379 | 9 |
| `test_04_system_designs_and_setback.py` | 560 | 14 |
| `test_05_contractors_and_construction_permits.py` | 429 | 11 |
| `test_06_inspections.py` | 346 | 8 |
| `test_07_operating_permits_and_pumping.py` | 254 | 6 |
| `test_08_repair_orders.py` | 409 | 9 |
| `test_09_transfer_inspections.py` | 542 | 11 |
| `test_10_authorization_and_reporting.py` | 155 | 5 |
| `test_11_stale_reads_and_refusal_order.py` | 345 | 6 |

## Coverage

- **Queue A (Difficulty):** 19/19 instances translated, every one with ≥2 tests (38+ tests). 0 skipped.
- **Queue B (Corner):** 61/61 non-stub instances translated, ≥1 test each. 0 skipped.
- **Stubs:** 7 `excluded_because:` entries correctly **not** translated; all 7 `difficulty_instance` cross-references verified to resolve to real names in the difficulty index.

## Skip list

**Empty** — no instance failed the PRD-first two-condition filter. Every rule the indices assert is verbatim-stated and uniquely derivable in `workspace/PRD.md`.

## Verification performed

- **Citation audit (automated):** 203 PRD quotes extracted from docstrings and whitespace-normalised `grep`-matched against `PRD.md` — **0 non-verbatim**, 0 tests without a quote.
- **Tag audit (automated):** all 101 tests carry exactly one `Design:` line; 0 untagged, 0 dual-tagged, 0 unknown tags.
- `pytest --collect-only` → 101 collected, no errors. `pyflakes` clean over `test_suite/`.
- No `skip`/`skipif`/`xfail` anywhere; no "scaffold" references in generated code.

## Two findings worth relaying

1. **`corner_pumper_without_pumper_license_class_is_rejected` has an unreachable setup as written.** Its trigger uses `pumped_on: 2026-05-03` while the clock is at the 2026-05-01 default. PRD §3.7 says a future-dated pump-out "is a malformed request and draws `ERR_INVALID_REQUEST`", and check 5 (shape, 400) sits *above* check 7 (licence class, 403) in the §2.6 ladder — so both trigger calls would have returned `ERR_INVALID_REQUEST`, not the asserted `ERR_LICENSE_CLASS_MISMATCH`. I repaired the fixture with a clock advance to `2026-05-03` (minimal change, preserves every pre-computed literal including `next_pumping_due_on == 2029-05-03`). File: `test_suite/test_07_operating_permits_and_pumping.py`.

2. **`corner_entity_version_increments_on_every_mutation` carries one unfalsifiable assertion.** It asserts "`updated_at` advances" across two fee payments, but the logical clock never moves between them, so per PRD §2.4 (`updated_at` is *the logical-clock instant* of the last mutation) the value is necessarily identical. I translated the instance's derivable claims (`version` 1→2→3, ledger totals, `created_at` unchanged) and did not assert the advancing `updated_at`.

**Orchestrator post-check**: 101 tests collected on disk across 11 files; `grep` for `pytest.mark.skip|pytest.mark.xfail|skipif` over `test_suite/` + `test_helpers/` → 0 hits. ✔

## Step 6: Generate implementation — 2026-07-26T14:05:00.000Z

Implementation complete and verified.

## Files written (`workspace/implementation/`)

| File | Lines |
|---|---|
| `app.py` | 69 |
| `auth.py` | 35 |
| `calc.py` | 332 |
| `derive.py` | 247 |
| `errors.py` | 104 |
| `lookup.py` | 56 |
| `response.py` | 39 |
| `serialize.py` | 251 |
| `store.py` | 48 |
| `util.py` | 137 |
| `validate.py` | 170 |
| `routes/__init__.py` | 0 |
| `routes/parcels.py` | 156 |
| `routes/contractors.py` | 75 |
| `routes/wells.py` | 122 |
| `routes/site_evaluations.py` | 163 |
| `routes/system_designs.py` | 149 |
| `routes/construction_permits.py` | 139 |
| `routes/inspections.py` | 195 |
| `routes/operating_permits.py` | 116 |
| `routes/pumping_records.py` | 79 |
| `routes/repair_orders.py` | 156 |
| `routes/transfer_inspections.py` | 143 |
| `routes/misc.py` | 87 |
| `start.sh` (exec, guarded pip, `$PORT`, 0.0.0.0, foreground) | 9 |
| `requirements.txt` | 1 |

**Routes: 53 registered vs 53 scaffold endpoints** (exact 1:1 match, verified from `app.url_map`). `python3 -m py_compile` passes on every source file. Store is empty at boot — no seeding anywhere.

## Trap avoidance (all three confirmed)
- **Timestamps** — one renderer, `util.render_dt`, emits `%04d-...T...%02d.%03dZ`; every serialized datetime field routes through it. `grep -rn "utcnow|isoformat|strftime|datetime.now|time.time|fromtimestamp"` returns **zero hits**; the only `datetime(` constructions are the default logical clock and the ISO parser. All server-stamped instants come from `util.now()` (logical clock, default `2026-05-01T00:00:00Z`), and derived dates (`valid_until`, `next_pumping_due_on`, `compliance_deadline`, `expires_on`, `certificate_valid_until`…) are computed from clock-derived datetimes, so they render identically. A recursive audit over every entity payload in a full end-to-end run found no non-conforming timestamp string.
- **UUIDs** — `str(uuid.uuid4())` only (`uuid4().hex` appears nowhere but in a warning comment).
- **Keep-alive** — `after_request` sets `Connection: close`; confirmed present on a live HTTP response from a real `bash start.sh` boot on `0.0.0.0:$PORT`.

## Verification performed
Four scratch suites (`/tmp/smoke{,2,3,4}_0856.py`, ~300 assertions) all pass, covering: exact-decimal drainfield sizing (360/0.60 = exactly 600), per-line-item fee rounding (48038+24980+32025+16013 with variance), inclusive setback equality, sticky variance verdicts cleared only by a new well, void money/flow conservation, closed-interval permit-window adjacency conflict vs half-open contractor calendar with the 45-minute trailing buffer (exact adjacency allowed, one minute earlier rejected), segregation-of-duties ahead of state checks, pumping tier boundaries and 90/91/0-day compliance edges, calendar-month deadline advance, groundwater cascade (advisory → parcel flag → monitoring → halved interval → compliance), repair-order branch divergence (reinstate vs revoke), transfer grade variants including the FIELD_VERIFIED DUE_SOON upgrade, OCC 412s, and refusal-ladder precedence (401→403→404-body-FK→400→ownership→OCC→state→…→402).

Two judgement calls worth flagging: submitting a site evaluation as a non-evaluator returns `ERR_UNAUTHORIZED` (PRD states the rule but assigns no error id), and certifying a `BLOCKED` transfer returns `ERR_INVALID_STATE` (check 10 precedes check 11 in §2.6, though §3.9's prose explains it via the permit not being active). Also reaped a stray orphan Flask server left over from an earlier attempt at this task directory.

**Orchestrator post-check**: `app.url_map` → 53 method-route pairs == 53 SCAFFOLD endpoints; `python3 -m py_compile` clean over all 24 source files. ✔

## Step 7: Run tests and iterate — 2026-07-26T14:22:00.000Z

Clean. No orphan servers from this task; the remaining `app.py` processes belong to other tasks' concurrent sweeps.

## Result: green on the first 8-round sweep — 0 iterations of fixes required

**Iterations run:** 1 (a single 8-round stability sweep; no failures surfaced, so the diagnostic protocol was never entered).

**Tests deleted:** none. No test failed in any round, so no STEP 1 coverage / unique-derivability adjudication was triggered.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none.

**Final per-round tallies** (`workspace/implementation/results.{1..8}.json`):

| round | total | passed | failed | errors |
|---|---|---|---|---|
| 1 | 101 | 101 | 0 | 0 |
| 2 | 101 | 101 | 0 | 0 |
| 3 | 101 | 101 | 0 | 0 |
| 4 | 101 | 101 | 0 | 0 |
| 5 | 101 | 101 | 0 | 0 |
| 6 | 101 | 101 | 0 | 0 |
| 7 | 101 | 101 | 0 | 0 |
| 8 | 101 | 101 | 0 | 0 |

`ALL_GREEN` from the harness summary. Each results file independently confirms `len(tests) == 101` with every outcome `passed`, so the tallies are not a truncated-collection artifact.

**Integrity audit performed alongside the sweep** (all clean):
- No `pytest.mark.skip` / `xfail` / `skipif` anywhere in `test_suite/` or `test_helpers/`.
- Test count reconciles per file: 13+9+9+14+11+8+6+9+11+5+6 = 101 across the 11 modules.
- Known domain trap (i) — wall-clock leakage: `grep` for `utcnow|datetime.now|time.time()|isoformat|strftime` over `workspace/implementation/` returns zero hits; all instants route through the logical clock and the single `util.render_dt` renderer.
- Known domain trap (ii) — `uuid4().hex`: only `str(uuid.uuid4())` at `workspace/implementation/util.py:84`.
- Werkzeug keep-alive mitigation still in place: `resp.headers["Connection"] = "close"` at `workspace/implementation/app.py:58`.
- No persistence or seeding: zero hits for `sqlite` / `json.dump` / `open(` in the implementation — storage is in-memory dicts only, so `start.sh` re-invocation under `per-test-server` wipes all state.

**Note on host conditions:** the sweep ran while two sibling tasks (`task_0852`, `task_0854`) were executing their own 4-way waves, pushing load to ~8 on an 8-core host. Despite that contention all 8 rounds still came back clean with zero boot-timeout ERRORs, which makes the green result a conservative rather than a lucky one.

**Orchestrator independent re-verification** (did not trust the subagent's claim): re-parsed all 8 `results.N.json` directly — every round `total=101 passed=101 failed=0 errors=0 skipped=0`, `len(tests)==101`, per-test `status` histogram `{'passed': 101}` with zero zero-duration entries, and an identical test-name set across all 8 rounds. Round wall times 84.9–86.3 s (wave 1) and 59.4–59.9 s (wave 2), consistent with a genuine per-test-server run. `grep` for `mark.skip|mark.xfail|skipif|pytest.skip(` over `test_suite/` + `test_helpers/` → 0 hits; `pytest --collect-only` → 101 collected; 101 `def test_` on disk (no silent deletions). Sweep harness: `sweep.sh` (2 waves of 4, no inline pkill, verbatim `cd <impl> && bash start.sh`). ✔

## Step 8: Finalize PRD — SKIPPED — 2026-07-26T14:23:00.000Z

Skip condition met: Step 7 exited on the FIRST 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes and 0 `implementation/` fixes. `PRD.md` already determined every behavior the implementation exhibits at the sites the test suite exercised, so no `PRD_FINALIZED.md` is produced. Step 9 consumes `PRD.md` directly.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-07-26T14:35:00.000Z

Done. `workspace/PRD_COMPLETED.md` is written.

## Summary

**Source vs. output:** PRD.md 447 lines / 93,824 chars → PRD_COMPLETED.md 449 lines / 103,528 chars (**+2 lines, +9,704 chars**). All section headers and all 101 table rows are byte-identical; every change is an in-paragraph insert or revision (35 lines revised, one 2-line paragraph added in §2.8). No new sections.

**Counts:** 33 changes — **26 ambiguity-pins**, **7 mismatch-revisions**.

Both spots the impl-generator flagged were confirmed in the code and pinned: `site_evaluations.py:107-109` (`ERR_UNAUTHORIZED`, and it fires ahead of the state and valid-hole checks) and `transfer_inspections.py:118-119` (`ERR_INVALID_STATE`, never `ERR_OPERATING_PERMIT_NOT_ACTIVE`).

### Changes

- §2.1 — revise — ambiguity — headers refused when empty, not merely absent — `auth.py:31`
- §2.2 — revise — ambiguity — `api_request_timestamp` read from the logical clock, not wall-clock — `response.py:10`
- §2.3 — revise — ambiguity — non-integer `limit`/`offset` also `ERR_INVALID_REQUEST` — `validate.py:135-148`
- §2.3 — insert — ambiguity — `created_at` ties broken by insertion order (common under the logical clock) — `store.py:46-48`
- §2.3 — insert — ambiguity — filter values never validated (match nothing); `transfer_hold` accepts only true/false/1/0 — `parcels.py:68`, `validate.py:156-165`
- §2.5 — insert — ambiguity — backwards clock moves permitted; re-run derivations but never reverse a recorded expiry — `misc.py:61-85`
- §2.6 ch.1-2 — insert — ambiguity — the site-evaluation submitter identity test rides after check 3 — `site_evaluations.py:107`
- §2.6 ch.4 — insert — ambiguity — multi-FK resolution order; absent FK is check 5 **except** operating-permit issue → 404; non-string FK → 404 — `operating_permits.py:26`, `lookup.py:8`
- §2.7 — insert — **mismatch** — "supersedes" is commercial, not a register action: neither OCC operation touches the displaced record — `system_designs.py:41-63`, `transfer_inspections.py:56-77`
- §2.8 — insert — ambiguity — explicit integer-vs-number list for all 21 numeric body fields — `validate.py:54-77`
- §2.9 — revise — **mismatch** — cascades bump only records that actually move; no-op re-derivation bumps nothing; fee payment / transfer request bump unconditionally — `derive.py:148`, `parcels.py:155`
- §3.1 — revise — ambiguity — `lot_size_sqft` must be a whole number — `parcels.py:32`
- §3.1 — revise — ambiguity — `amount_cents` non-negative integer (zero accepted); fee payment answers 200 — `parcels.py:150,156`
- §3.1 — revise — ambiguity — dossier `latest_certificate_grade` tie-break = later-created — `parcels.py:126`
- §3.2 — insert — ambiguity — sample posting always stamps + bumps the well even when no posture moves; `last_sample_collected_at` overwritten out of chronological order — `wells.py:111-115`
- §3.2 — insert — ambiguity — non-ACTIVE permits skipped and never pick it up; `monitoring_required` is one-way and never cleared — `derive.py:231-237`
- §3.3 — insert — ambiguity — any DesignProfessional may append; `hole_number` free/non-unique; unbounded drop/elapsed; append answers 200 — `site_evaluations.py:77-100`
- §3.3 — insert — **ambiguity (flagged (a))** — non-evaluator submit → `ERR_UNAUTHORIZED`, ahead of state and valid-hole checks — `site_evaluations.py:107-109`
- §3.3 — revise — ambiguity — omitted `review_note` overwrites with null — `site_evaluations.py:128,139,144`
- §3.4 — insert — ambiguity — the draw imposes no status/lapse gate on the evaluation — `system_designs.py:26-63`
- §3.4 — insert — ambiguity — non-`VARIANCE_REQUIRED` posture on a variance decision → `ERR_INVALID_STATE`, after the lifecycle test — `system_designs.py:132-135`
- §3.4 — revise — **mismatch** — design-submit preconditions reordered to ladder order (approved → setback → lapse) — `system_designs.py:79-86`
- §3.4 — insert — **mismatch** — soil beats setback on design approval — `system_designs.py:107-110`
- §3.5 — revise — **mismatch** — licence-status edges *do* carry source-state preconditions → `ERR_INVALID_STATE` — `contractors.py:61-73`
- §3.5 — insert — ambiguity — permit-number sequence counts permits ever issued; never reused after void/expiry — `construction_permits.py:61-62`
- §3.5 — revise — ambiguity — void `reason` required string, may be empty — `construction_permits.py:116`
- §3.6 — insert — ambiguity — `VOIDED` permit bars booking with `ERR_INVALID_STATE`, ahead of calendar/window; no other status bars it — `inspections.py:53-54`
- §3.6 — revise — ambiguity — `deficiency_codes` ignored on a pass; inspection status tested before permit status — `inspections.py:113,128-131`
- §3.6 — insert — **mismatch** — the three pass conditions run in reverse of the described order; SoD sits above every state check — `inspections.py:121-146`
- §3.7 — insert — ambiguity — no uniqueness bar on a second operating permit per construction permit — `operating_permits.py:21-56`
- §3.7 — insert — ambiguity — unknown pumper → `ERR_LICENSE_CLASS_MISMATCH`; no gate on hauler `effective_status` or permit status — `pumping_records.py:34-36`
- §3.8 — insert — ambiguity — extension cap tested before the imminent-hazard bar — `repair_orders.py:110-113`
- §3.8 — insert — **mismatch** — ESCALATE revokes from any status, not only ACTIVE/SUSPENDED — `repair_orders.py:151`
- §3.9 — insert — ambiguity — parcel and operating permit are not cross-checked on a transfer request — `transfer_inspections.py:29-30`
- §3.9 — insert — **ambiguity (flagged (b))** — certifying a `BLOCKED` transfer → `ERR_INVALID_STATE`; certify declared only from `REQUESTED` — `transfer_inspections.py:118-119`

**Orchestrator post-check**: `PRD_COMPLETED.md` present (449 lines / 103,528 chars); markdown header list byte-identical to `PRD.md` (no sections added or dropped); §4 endpoint rows 53 == 53 and §5 error rows 44 == 44 preserved; zero occurrences of the token "scaffold". `PRD_FINALIZED.md` correctly absent (Step 8 skipped). ✔

---

# PIPELINE COMPLETE — task_0856_septic_onsite_wastewater

Steps 1–9 all done (Step 8 legitimately skipped). Final state: 101/101 tests passing across all 8 stability rounds, clean on the FIRST sweep with 0 deletions and 0 fixes.
