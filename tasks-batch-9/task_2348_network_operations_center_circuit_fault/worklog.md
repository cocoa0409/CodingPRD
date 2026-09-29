# Worklog — task_2348_network_operations_center_circuit_fault

## Step 1: Create task directory — 2026-09-02T03:17:25.339Z

Created `tasks/task_2348_network_operations_center_circuit_fault/` and `tasks/task_2348_network_operations_center_circuit_fault/workspace/` (pre-allocated task name used verbatim; no index scan performed).

## Step 2: Generate scaffold — 2026-09-02T04:41:00.000Z

All three artifacts are complete and the linter is clean.

Verdict block (verbatim):

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2348_network_operations_center_circuit_fault/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2348_network_operations_center_circuit_fault/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2348_network_operations_center_circuit_fault/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    60
  §1.1 entities declared:     15
  §1.8 instances scanned:     18
  §1.9 instances scanned:     43
  Calls scanned (§1.8+§1.9):  633

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_2348_network_operations_center_circuit_fault/`):

- `SCAFFOLD.yaml` (§1.0–§1.7, no design keys): 15 entities, 12 state machines, 2 OCC concurrency rules, 12 calculations, 61 ordered validations, 60 endpoints, 72 errors, 6 roles. complexity_profile: primary `graph_constraint` / secondary `temporal_windowing`, layers `cascading_side_effects, rate_threshold_triggers, optimistic_concurrency, derived_field_reconciliation`, topology `graph`, shape `cyclic`, role_model `segregation_of_duties`, consistency `immediate`.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`): all 9 §0.5 rules × 2 differentiated instances = 18.
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`): all 9 claim-extraction-guide sections, 58 instances total — 43 with full `test_recipe` (entities 10, state_machines 8, calculations 4, validations 8, endpoints 3, errors 2, rbac 6, cross_cutting_complexity_layers 2, consistency_model 1) plus 15 `excluded_because` stubs citing §1.8 instances by name (all citations verified to resolve, no name collisions across the two design files).

Two internal defects found and fixed while grounding §1.9:
- `alarm_correlation_assignment` set `incident_id = NULL` for SUPPRESSED alarms, contradicting the `POST /alarms` side effect and the `Incident.alarm_count` definition ("count of Alarm rows whose incident_id equals this incident"). The suppressed branch now files the alarm under `parent.incident_id`; the maintenance-suppressed branch remains the genuine no-incident case.
- Corrected numbers I had initially mis-derived while drafting corner instances: single-BRONZE-path incidents score `impact_score 20 / SEV3` (not 18), the GOLD 330-minute outage yields `credit_amount_cents 92000` (2 breach hours at 10 pct of 920000, not 46000), and the dual clocks measure `restored_at − opened_at` / `restored_at − detected_at` (50.00 / 60.00 in that fixture, not to `confirmed_at`).

No sibling task directory was read at any point; the scaffold was derived only from the scenario text plus the generator skill and its claim-extraction guide.

## Step 3: Copy shared files — 2026-09-02T04:41:05.000Z

Copied `INSTRUCTION.md` from project root to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-02T05:15:00.000Z

PRD generation complete.

**Output:** `workspace/PRD.md` — 417 lines.

**Sections covered**
- §1 Introduction (3 paragraphs, domain framing only)
- §2 Global Specifications, 11 subsections: 2.1 identity/roles/carrier scope · 2.2 response envelope (byte-for-byte verbatim from `section-2.2-response-structure.md`, diff-verified) · 2.3 pagination and list ordering · 2.4 logical clock · 2.5 identity/timestamps/versioning · 2.6 stale-parent rejection (both OCC rules) · 2.7 the 16-band refusal ladder covering all 61 validations with error ids, statuses and applies_to scopes · 2.8 nested reads · 2.9 precision and rounding · 2.10 conserved ledgers and re-derivation · 2.11 segregation of duties
- §3 Business Logic, 8 subsections: 3.1 carriers/circuits/devices · 3.2 paths, legs, posture derivation and the availability report · 3.3 alarm ingestion, correlation, clearing cascade · 3.4 incident classification, response clock, escalation, chronic re-evaluation, reopen · 3.5 carrier tickets, evidence, tier escalation, dual-clock restoration · 3.6 SLA credit claims and carrier exposure · 3.7 maintenance windows and failover verification · 3.8 capacity pressure, upgrade orders, vendor scorecard
- §4 API Endpoints: lead paragraph plus a 4-column, 60-row table in scaffold order
- §5 Error Codes: 2-column, 72-row table. Document ends at §5 with no audit footer.

**Hard-contract audits (mechanically executed, two passes on Contract 1)**

```
Field coverage check:
- entities[].fields: 133 required, 133 present, 0 missing
- endpoints[].request_body: 77 required, 77 present, 0 missing
- endpoints[].query_params: 37 required, 37 present, 0 missing
Status: PASS
```
```
Rule coverage check:
- validations[] with priority: 61 checked, 61 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed, 0 missing
- state_machines[].transitions: 66 checked, 66 fully expressed, 0 missing
- calculations[]: 12 checked, 12 fully expressed, 0 missing
- validations[] conditions: 61 checked, 61 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 37 side-effect sets + 61 applies_to scopes checked, all expressed, 0 missing
- entities[].fields[] structured content: 156 checked, 156 reconstructible from prose, 0 missing
- sibling-branch symmetry: 16 groups checked, 16 with equal prose density, 0 asymmetric
Status: PASS
```
```
Path purity check (§3 only):
- backtick tokens scanned: 1027
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional verifications: all 72 scaffold error ids appear and no invented `ERR_` token exists; availability outputs (`period_minutes`, `path_down_minutes`, `availability_pct`, `leg_down_minutes`) and clock output `current_utc` all named; no fuzzy quantity words; only fenced code blocks are the two inside the verbatim §2.2 block.

**Scaffold inconsistencies resolved by explicit decision:** alarms/test results/capacity readings carry no `version` (declared `common_fields: false`), so the endpoint text claiming an alarm version bump was not transcribed; mitigation de-escalation follows the state machine (`EXEC → L2`, `L2 → L1` only); `fail_test_count` increments on `FAIL` or `INCONCLUSIVE`; `REMEDIATION_PLAN` and `REPLACE` both set `watchlist_state` to `WATCHLIST`; failover-start preconditions ordered by validation priority; the soak-elapsed and no-open-alarm checks guard only the accept branch of restoration confirmation; device health has no degraded value.

Neither design yaml was opened, grepped or referenced, and no sibling task directory was read.

## Step 5: Generate unit tests — 2026-09-02T06:50:00.000Z

All twelve suite files are on disk and the coverage audit closes clean. Final state:

## Files written

- `test_helpers/` (9 modules): `__init__.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`
- `test_suite/`: `conftest.py` plus 12 test modules — `test_01_estate_registration.py` (9), `test_02_alarm_ingestion_and_correlation.py` (9), `test_03_incident_lifecycle.py` (5), `test_04_carrier_ticket_evidence_and_tiers.py` (7), `test_05_restoration_clocks.py` (5), `test_06_credit_claim_arithmetic.py` (11), `test_07_path_posture_and_availability.py` (5), `test_08_maintenance_window_coordination.py` (6), `test_09_failover_verification.py` (5), `test_10_capacity_upgrades_and_vendor_scorecard.py` (10), `test_11_access_control_and_carrier_scope.py` (9), `test_12_optimistic_concurrency.py` (4)

## Test count

**85 tests**, all collected by pytest (`85 tests collected`), each carrying exactly one `Design:` line as the final line of its docstring.

## Instances translated vs skipped

- Queue A (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`): 18 instances, 0 stubs — **18/18 translated**, every one with >=2 tests.
- Queue B (`SCAFFOLD_CORNER_DESIGN.yaml`): 58 instances of which 15 carry `excluded_because:` — **43/43 non-stub instances translated**, >=1 test each.
- **Skipped for PRD-filter failure: none.** The only exclusions are the 15 design-declared stubs, which are not test sources.

Three instances whose design-declared HTTP status conflicted with the PRD's registered status map are asserted via `validate_error(resp, ApiErrorId.X)` without an explicit status, so the PRD's own status table arbitrates; two others had a `device_role: "ROUTER"` literal that is not in the PRD enum and were built with `EDGE`.

## Coverage audit result

```
queue A instances 18 stubs 0    -> uncovered: []   (none with <2 tests)
queue B instances 58 stubs 15   -> uncovered: []
tests 85 / tags 85 / distinct instances 61 (18 A + 43 B)
bad tag structure: []   tags pointing at stubs or non-existent instances: []
```

Supporting audits: `pyflakes` clean on all 13 `test_suite/*.py` files; every `PRD n.n: "..."` citation survives a literal substring match against `workspace/PRD.md`; every name imported from `test_helpers` resolves to a real export; no file in `test_suite/` or `test_helpers/` mentions "scaffold". Suite not executed against a server (implementation was under concurrent generation); verification was static plus hand-recomputation of every asserted figure.

## Step 6: Generate implementation — 2026-09-02T06:50:05.000Z

The implementation is complete and verified.

## Files written
- **Launcher/deps:** `start.sh` (honors `PORT`, default 10000, binds `0.0.0.0`, guarded `pip install`, `exec python3 app.py`), `requirements.txt`
- **Foundation (10 modules):** `app.py`, `db.py` (in-memory dicts + logical clock pinned to `2026-08-01T00:00:00Z`), `errors.py` (~75 error ids -> status), `consts.py`, `timeutil.py`, `response.py`, `middleware.py` (auth, role matrix, carrier scope), `valid.py`, `serialize.py`, `calc.py`, `lookup.py`, `derive.py` (all cascades: correlation, posture/SPOF, incident classification, restoration clocks, credit arithmetic, chronic re-evaluation, ledgers, vendor scorecard)
- **Routes (15 modules):** `routes/__init__.py`, `_common.py`, `carriers.py`, `circuits.py`, `devices.py`, `paths.py`, `segments.py`, `alarms.py`, `incidents.py`, `tickets.py`, `claims.py`, `windows.py`, `failover.py`, `orders.py`, `reviews.py`, `clock.py` — 3,844 lines total

## Endpoint count
**60 registered routes — an exact set-equality match with the PRD §4 table** (diffed both directions).

## Boot + smoke confirmation
Booted repeatedly from a fresh `bash start.sh`; each boot starts with an empty store and the logical clock at `2026-08-01T00:00:00.000Z` — nothing seeded. A 49-step end-to-end scenario passes with zero failures, covering the full estate/alarm/incident/ticket/claim/window/failover/capacity/vendor chain, plus 401/403/404/405/400 generic behaviour and list `meta` pagination.

## One defect found and fixed
`PRD.md:21` requires a `CarrierLiaison`'s **reads** be scoped to its own carrier; GET handlers were unscoped. Added `scope_read()` / `liaison_carrier_id()` to `middleware.py`: single-object reads of a foreign carrier/circuit/ticket/test-result/claim/window now return 403 `ERR_CARRIER_SCOPE_VIOLATION`, list reads are narrowed to the acting carrier. Unknown ids still 404 (lookup precedes scope check); non-liaison roles unaffected.

Two apparent failures turned out to be correct per PRD: `ERR_CLAIM_ALREADY_OPEN` includes `PAID` claims (§3.6), and `NONE -> L1` escalation has no dwell requirement (§3.4).

## Step 7: Run tests and iterate — 2026-09-02T08:05:00.000Z

All 8 parallel rounds are green (85/85 each).

## Summary

**Iterations run:** 3 sweeps (8 parallel rounds each).

**Tests deleted:** none. Every failure traced to a test_helpers bug (STEP 2), not to PRD silence — no test asserted a scaffold-only or non-uniquely-derivable rule.

**Fixes applied to `test_helpers/`** (3, all in the same layer the triage hint pointed at — 29 of 85 tests shared one root cause):

1. `test_helpers/assertions.py` — added a `validate_success(response, expected_status)` wrapper (shadowing the framework export via the existing `from .assertions import *`). The framework helper returns `body["data"]`, but all 30 call sites in `test_suite/` read the full envelope (`validate_success(resp, 201)["data"]`, `["meta"]`), so every one of them died with `KeyError: 'data'`. The wrapper runs the identical structural checks and returns `response.json()`. No assertion was weakened — the envelope validation still runs.
2. `test_helpers/factories.py` -> `circuit_payload` — the factory's own docstring contract is "passing `None` for an optional field removes it", but `mrc_cents`/`bandwidth_mbps`/site codes were named parameters written unconditionally into the payload, so `mrc_cents=None` sent `"mrc_cents": null` instead of omitting the key. `test_circuit_without_a_monthly_charge_is_rejected` self-checked `assert "mrc_cents" not in payload` and tripped. Now every `None`-valued field is omitted, which is what the PRD's required-field-missing branch actually needs.
3. `test_helpers/api_client.py` -> `ApiClient.__init__` — set `Connection: close` on the session. The module-level `api_client` holds one `requests.Session`, and `--isolation per-test-server` SIGKILLs the server between tests, so the pooled keep-alive socket was already dead when the next test reused it (`ConnectionResetError` / `RemoteDisconnected` mid-fixture). This was the residual flakiness in sweep 2 (2 failures across 680 test executions, different tests each time, both non-assertion transport errors). Each request now opens a fresh socket.

**Fixes applied to `implementation/`:** none. No failure survived to STEP 3 — the implementation was already PRD-faithful on all 85 assertions, and no PRD-required check was removed or weakened.

**Flakiness note:** `test_first_resolution_counts_one_fault_and_stays_normal` failed once in sweep 1 and `test_skipping_a_carrier_tier_is_refused` / `test_maintenance_suppressed_circuit_blocks_the_ticket` once each in sweep 2; all three were the stale-keep-alive-socket class of failure, and all are stable across sweep 3's 8 rounds.

### Orchestrator independent verification (the subagent left no results files on disk)

The orchestrator re-ran the 8-round parallel sweep twice itself (16 rounds, 1360 test executions). Result: `failed == 0` in every single round — zero assertion failures, zero HTTP-response mismatches. The only non-passing entries were 3 `errors` (one each in three different rounds, a different randomly-chosen test each time) whose detail was always the runner's own port-cleanup subprocess exceeding its hardcoded 5s budget:

```
failed on setup with "subprocess.TimeoutExpired: Command 'pids=$(lsof -ti:43765 -sTCP:LISTEN 2>/dev/null); [ -n "$pids" ] && kill -9 $pids 2>/dev/null; true' timed out after 5 seconds"
```

This is a harness/host-load artifact under 8x concurrency, not a defect in `implementation/`, `test_suite/` or `test_helpers/`, and per the skill's own guidance was re-run rather than "fixed". Rounds re-run individually at lower load come back 85/85.

## Step 8: Finalize PRD — 2026-09-02T08:35:00.000Z

## Result

`workspace/PRD_FINALIZED.md` created — **byte-identical to `PRD.md`** (md5 `2220b558...`).

- PRD.md: 417 lines · PRD_FINALIZED.md: 417 lines · **delta 0 lines (0.00%)**
- Changes: **none.** All three Step 7 fixes were fixture/transport bugs in `test_helpers/`; none revealed PRD silence or a PRD/implementation mismatch, and zero `implementation/` fixes and zero test deletions were recorded.

## Per-item investigation log

**Item 1 — `test_helpers/assertions.py::validate_success` wrapper (envelope vs `data`)**
- (a) Subject: the success-response envelope shape (`meta` / `response_type` / `data`) and the return contract of a test helper.
- (b) Enumerated/read: `implementation/response.py` (all four emitters — `object_response`, `array_response`, `error_response`, `paginate`), the `errors.py`-driven error path via `error_response`, and `test_helpers/assertions.py`.
- (c) No wording change. The impl emits exactly what PRD §2.2/§2.3 already pin: `response_type` `object`/`array`/`error`, error `meta` limited to `api_request_id` + `api_request_timestamp`, error `data` limited to `error_id` + `message`, `api_request_id` prefixed `req_`, and the four pagination fields on list responses only (`has_more = offset + len(items) < total_count`). The failure was purely a helper-signature bug, invisible to the server.

**Item 2 — `test_helpers/factories.py::circuit_payload` `None`-omission**
- (a) Subject: how the server treats a required/optional body field supplied as JSON `null` versus omitted, on circuit creation.
- (b) Enumerated/read: `implementation/valid.py` — `_present()` (`key in b and b[key] is not None`) and all 13 consumers; `implementation/routes/circuits.py:27-75` (`create_circuit`); the tripping test `test_suite/test_01_estate_registration.py:187-217`.
- (c) No wording change, and none warranted: `_present` maps explicit `null` to "absent" uniformly across the whole validation layer, so `{"mrc_cents": null}` and an omitted key both produce `ERR_INVALID_REQUEST` — the pre-fix and post-fix payloads are behaviorally indistinguishable to the server. Only the test's own in-test guard `assert "mrc_cents" not in payload` failed, before any HTTP call. PRD §2.7 band 6 plus §3.1 already determine the observed behavior. (Recorded for Step 9: the `null`-for-an-*optional*-field path, e.g. `{"monitoring_state": null}` -> defaults to `UNMONITORED` rather than 400, is a genuinely under-determined corner of PRD §2.7, but is off the Step 7 site and out of Step 8's HARD SCOPE.)

**Item 3 — `test_helpers/api_client.py` `Connection: close`**
- (a) Subject: HTTP transport / connection reuse across per-test server restarts.
- (b) Enumerated/read: `implementation/app.py`, `implementation/start.sh`, `implementation/middleware.py` (no keep-alive, socket or connection-lifetime logic anywhere; Flask/Werkzeug default behavior only).
- (c) No wording change. Root cause is the module-level `requests.Session` reusing a socket the harness had already SIGKILLed under `--isolation per-test-server`; the server exhibits no behavior here to describe. Adding any sentence would invent behavior.
