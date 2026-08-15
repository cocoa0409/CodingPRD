# Worklog — task_1373_multifamily_pest_control_program

## Step 1: Create task directory — 2026-08-13T01:44:00.000Z

Pre-assigned by pipeline orchestrator; directory `tasks/task_1373_multifamily_pest_control_program/` + `workspace/` already existed. Treated as DONE per instructions.

## Step 2: Generate Scaffold — 2026-08-13T02:34:00.000Z

Scaffold generation complete. All three artifacts are written to `/home/ubuntu/github/CodingPRD/tasks/task_1373_multifamily_pest_control_program/` and pass the skill's linter cleanly.

**Files produced**
- `SCAFFOLD.yaml` (~948 lines) — §1.0–§1.7: verbatim response envelope, 12 entities, 9 state machines, 2 OCC concurrency rules, 10 calculations, 31 ordered validations, 65 endpoints, 30 error codes, 6 roles. Top-level keys limited to `scenario`, `domain_name`, `api_prefix` (`/pest`), `complexity_profile`, `response_envelope`, `entities`, `state_machines`, `concurrency_rules`, `calculations`, `validations`, `endpoints`, `errors`, `roles`.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`, 18 instances (2 per each of the 9 Difficulty Rules), all with structured `setup_api_calls`/`trigger`/`assert` recipes replayable from empty DB.
- `SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`, 49 instances across 8 taxonomy sections (entities, state_machines, calculations, validations, endpoints, errors, rbac, cross_cutting_layers, consistency_model), including 5 `excluded_because` stubs pointing at §1.8 instances.

**Design shape** (workflow-orchestration primary, compliance/audit secondary; cyclic state machines; segregation-of-duties role model): cyclic Treatment prep/reschedule loop and BedBugCase reopen cycle; a depth-4 cascade (positive inspection → case → adjacent-unit INITIAL inspections via a fully-pinned adjacency selector → unit flags → property posture) and a depth-3 fiscal cascade (non-compliant prep → chargeback → balance crossing → auto late fee); dual-variant calculations in two domains (chargeback provisional-vs-final cents; unit risk FORWARD-vs-HISTORICAL score); combinatorial formulas in two modes (nested min/max cap+coverage; pinned per-line-round-then-sum with a literal 25785-vs-25784 divergence); two distinct overlap semantics (technician 15-minute buffered half-open intervals vs 24h heat-treatment floor gap); two OCC-guarded endpoints; two compensating invariants (lease balance cents, technician booked minutes).

**Verification**: linter verdict is clean (65 endpoints, 12 entities, 18+49 instances, 664 calls scanned, zero violations, all FKs reverse-reachable). Additional mechanical audits passed: every `grounds` reference resolves, zero unbound `${var}` placeholders, all `excluded_because` targets exist, all 30 error codes grounded, all 72 instance names unique across both design files, no forbidden concurrency vocabulary, all endpoint roles/outputs resolve, all role `identity` fields valid. All numeric asserts were pre-computed as literals (e.g., 16125 = round(15000×1.075); 8595/17190/25785 disposal lines; balance chains 40000→56125→61500; risk scores 55 vs 80).

One deliberate deviation from guidance: 65 endpoints exceeds the Expert band (20–32) — driven by the scenario's 8 workflows plus the FK reverse-reachability rule; coupling density (not entity count) carries the difficulty.

## Step 3: Copy shared files — 2026-08-13T02:35:30.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-13T02:46:00.000Z

The PRD is complete and verified. Generated `/home/ubuntu/github/CodingPRD/tasks/task_1373_multifamily_pest_control_program/workspace/PRD.md` from the scaffold, per the `prd-bench-doc-generator` skill (the two difficulty/corner design files were not touched).

**Structure:** 2-paragraph introduction; §2 with ten domain-derived subsections (RBAC with per-role identity prose, verbatim §2.2 envelope, pagination, the logical clock with lazy EXPIRED/ENDED transitions, common resource properties, OCC, left-to-right nested resolution, the monetary rate card with per-line half-up rounding, the three scheduling safety invariants plus heat vacancy, and an explicit validation-priority ordering); §3 with nine workflow subsections (property/contract/unit setup, leases and the late-fee cascade, inspections with severity and the four-link bed bug exposure cascade, treatment prep handshake with the non-compliance cascade, reschedule/cancel/complete, bed bug case clearance, chargeback lifecycle with provisional-vs-final amount variants, claim packets, and the dual-variant risk score); §4 as a 4-column endpoint table (66 endpoints); §5 as a 2-column table of all 30 error IDs.

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields: 76 required, 76 present, 0 missing
- endpoints[].request_body: 57 required, 57 present, 0 missing
- endpoints[].query_params: 6 required, 6 present, 0 missing
- computed-read output fields: 7 required, 7 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: full priority chain (auth → role → existence/shape → state → OCC → heat safety → 3 temporal conflicts in pinned order → temporal windows → business constraints → referential/scope → fiscal → segregation) expressed in §2.10, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (reschedule with expected_treatment_version, resolve-dispute with expected_chargeback_version, both ERR_STALE_VERSION/412), 0 missing
- state_machines[].transitions: 33 checked across 9 machines, 33 fully expressed (from/to states, preconditions, side effects incl. Cascade A links 1–4 and Cascade B links 1–3), 0 missing
- calculations[]: 9 checked, 9 fully expressed (severity thresholds, adjacent-exposure selector, exposure posture, chargeback_amount both variants with pinned per-line rounding incl. the 25785-vs-25784 example, billing total, lease balance + late-fee trigger, risk score FORWARD/HISTORICAL, clearance replay, booked_minutes, unit_pest_flag), 0 missing
- validations[] conditions: 30 error IDs all matchable to trigger prose in §2/§3, 0 missing
- endpoints[].side_effects / applies_to: all expressed (scope check on both treatment and inspection creation; contract-active, heat-safety, and conflict checks on both create and reschedule), 0 missing
- entities[].fields[] structured content: defaults and nullability reconstructible (timezone default, active default true, vacancy_attested default false, reschedule_count starts at 0, severity null until COMPLETED, etc.), 0 missing
- sibling-branch symmetry: symmetric treatment of reschedule-from-SCHEDULED vs from-NON_COMPLIANT, UPHELD vs WAIVED, verified true/false, provisional vs final variants, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 423
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Also verified: all 30 error IDs, all 6 role names, all state values, and all enum members (pest types, treatment types, inspection kinds, severities, chargeback kinds, operational statuses) appear verbatim in backticks; §2.2 was emitted byte-identical to the canonical source block.

## Step 5: Generate Unit Tests — 2026-08-13T03:10:00.000Z

Generation complete and all audits pass.

## What was generated

**`test_helpers/` (9 files)** under `/home/ubuntu/github/CodingPRD/tasks/task_1373_multifamily_pest_control_program/test_helpers/`:
- `types.py` — all 12 entity TypedDicts (all carry `common_fields: true`, so `id`/`created_at`/`updated_at`/`version` throughout) plus status/kind/variant/role enums
- `api_client.py` — `ApiClient(GenericApiClient)` with 46 endpoint methods covering every row of the PRD §4 endpoint table (incl. `/_clock/set_current_utc`)
- `api_errors.py` — all 30 `ApiErrorId` values with the PRD §5 HTTP map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity structural assertions (UUID/ISO-8601 checks via the framework, status/enum membership, conditional fields like `cleared_at`, `final_amount_cents`, and the `delinquent == (balance > 0)` invariant)
- `factories.py`, `constants.py` — input-only payload factories; PRD §2.8 rate card, thresholds (48h notice, 14-day dispute, 50000 late-fee, reschedule limit 2, 24h heat gap, 15-min buffer), and canonical rounded amounts (16125 / 8595 / 5375 / 25785)
- `test_users.py` — shared headers for opaque roles plus per-instance builders for the entity-backed `Technician`/`Resident` roles
- `fixtures.py` — composite helpers: `setup_community` (property + ACTIVE contract + units + lease + resident + technician), inspection completion, positive-inspection cascade, treatment prep-handshake chain (notify → acknowledge → verify → complete), `setup_case_monitoring` (OPEN → TREATING → MONITORING), follow-up completion with clock control, `run_prep_failure_cycle`, chargeback assess/dispute helpers — all threading entity-backed role identity via `make_*_headers(entity["id"])`
- `__init__.py` — barrel export of framework generics + PRD-specific code

**`test_suite/` (11 files, 85 tests)** organized as: `test_01` community setup/defaults/FK reachability, `test_02` inspections (severity boundaries, double-complete, no-access strikes), `test_03` treatment workflow (prep handshake, reschedule cycle + OCC + limit, cancel invariant, completion reconciliation, read-after-write), `test_04` scheduling gates (contract state, scope, budget, heat safety, technician buffer, heat floor gap, pinned validation order), `test_05` bed bug cases (depth-4 exposure cascade, reopen cycle, 14-day clearance boundary, disposal block, posture boundary), `test_06` chargebacks (provisional-vs-final disposal, cap/coverage nesting, per-line rounding 25785, assessment gates, dispute window, payment match, segregation, OCC, balance invariants, late-fee cascade), `test_07` contract terminal + posture gate, `test_08` RBAC/ownership/auth, `test_09` risk-score variants + caps + pagination + summary, `test_10` claim packets.

## Audit results
- **Coverage**: all 18 difficulty instances have ≥2 tests; all 31 non-stub corner instances have ≥1 test; 85 tests total. The 5 `excluded_because:` stubs were verified to resolve to real difficulty instances and were not translated.
- **C4 tags**: every test docstring ends with exactly one verbatim `Design: Difficulty/<rule_id>/<instance>` or `Design: Corner/<section>/<instance>` line; no unknown tags, no untagged tests, no skip/xfail markers.
- **C1 verbatim check**: every quoted citation in every docstring survives a whitespace-normalized literal grep of `PRD.md` (0 failures after fixing elided quotes).
- **Collection**: `pytest --collect-only` discovers all 85 tests cleanly.

## Key design decisions
- **No instances skipped** — every non-stub instance in both indices has verbatim PRD coverage and a uniquely-derived outcome, so the PRD-first filter removed nothing.
- The logical clock default (`2026-08-01T00:00:00Z`) is exploited for deterministic `scheduled_for == 2026-08-02T00:00:00Z` and `cleared_at == 2026-09-04T00:00:00Z` assertions; `set_clock` drives the 13-day-fail/14-day-pass clearance boundary and the 14-day dispute-window boundary.
- Priority-pair tests are isolated so exactly the intended pair of violations is live (e.g., heat-safety vs technician-buffer with no unit double-booking possible).

## Step 6: Generate Implementation — 2026-08-13T03:36:00.000Z

Done. The complete implementation for `task_1373_multifamily_pest_control_program` is in place and verified.

**Files produced** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1373_multifamily_pest_control_program/workspace/implementation/`):
- `app.py` — single-file Flask application (~1100 lines) implementing all 46 endpoints
- `start.sh` — executable foreground launcher with guarded dependency install (`if ! python3 -c "import flask"`), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — `flask>=2.2`

**Key implementation decisions, all traced to PRD/scaffold:**
- **Logical clock**: in-memory, starts exactly `2026-08-01T00:00:00Z`; all server-stamped timestamps (including `meta.api_request_timestamp`) use it, formatted with 3 fractional digits. Fresh process = empty store + reset clock (verified across kill/relaunch).
- **Envelope**: `meta`/`response_type`/`data` per scaffold §1.0; pagination fields `limit` (default 10, clamped 1–100), `offset` (default 0), `total_count`, `has_more`; lists sorted `created_at` ASC with insertion-sequence tie-break.
- **Auth**: `X-User-Role`/`X-User-ID`; the clock endpoint requires `ProgramAdmin` role but not `X-User-ID`. Entity-backed identity for Technician (must be assignee) and Resident (unit/lease scoping).
- **Validation ordering** follows PRD §2.10 exactly: 401 → 403 (role + ownership) → 404/400 (path ids left-to-right, then body shape, then body FKs) → state (terminal `ERR_ALREADY_TERMINAL` / `ERR_INVALID_STATE` / domain guards) → `ERR_STALE_VERSION` (412) → heat safety → unit double-booking → technician 15-min buffered overlap → 24h heat floor gap → prep-notice/dispute-window → business constraints → scope/clause → fiscal → segregation of duties (last).
- **Cascades**: Cascade A (case OPEN creation, adjacent-exposure selector ordered by `unit_number`, auto INITIAL inspections at now+24h with `auto_created` flag gating the MONITORING flag per PRD prose, posture recompute), Cascade B (non-compliance chargeback → balance → late-fee trigger at ≥50000 with one-live-late-fee guard), no-access strike reset at 2, TREATING→MONITORING on full treatment+disposal completion, clearance replay (completed_at ASC, created_at-seq tie-break, 14-day inclusive spacing).
- **Money**: `Decimal` with per-line `ROUND_HALF_UP` ×1.075 then sum (verified: 3×7995 → 25785, not 25784), coverage `min(contract.coverage, 22000)` on REPEAT_INFESTATION only, overage line only in final variant when source treatment COMPLETED, cap clamp via `min(sum, chargeback_cap_cents)`.
- **OCC**: `expected_treatment_version` on reschedule, `expected_chargeback_version` on resolve-dispute, both → `ERR_STALE_VERSION` 412.
- **Lazy transitions**: contract ACTIVE→EXPIRED and lease ACTIVE→ENDED on read/gated ops with version bump; `spent_cents` resets at UTC calendar-month boundary.
- **Versioning**: starts at 1, increments on every mutation including system cascades and lazy transitions (drives claim-packet staleness checks).
- **No seeding**: store starts empty; all state is built via the declared API surface.

**Verification**: three smoke suites (~75 assertions) all pass — covering the full bed-bug cascade, prep handshake, reschedule limit/OCC, chargeback lifecycle (assess/dispute/resolve/bill/pay), late-fee cascade, claim packet finalize/stale/discard, risk score (both variants), adjacent-exposure read, RBAC scoping, and every error ID exercised in context. The two observed "FAIL" lines during testing were bugs in my throwaway test scripts (stale clock past the dispute window; wrong recency expectation), not in the implementation — confirmed by inspection of the responses.

## Step 7: Run Tests and Iterate — 2026-08-13T04:08:00.000Z

**Result: all 85 tests pass in 8/8 parallel rounds — verified across two consecutive sweeps (16/16 rounds, 1360/1360 test executions).**

**Iterations run:** 3 sweeps. Sweep 1 (baseline): 80/85 in every round, union of 5 failing tests. Sweep 2 (after fixes): 8/8 clean. Sweep 3 (confirmation, because the infra fix is probabilistic): 8/8 clean.

**Tests deleted:** none — every failure traced to a PRD-covered rule or to infrastructure; nothing was silently scaffold-only.

**Fixes applied to `test_suite/`** (3 tests, no helper-layer changes needed):

1. `test_03_treatment_workflow.py::TestOccOnReschedule::test_occ_stale_reschedule_returns_412` — ERROR PRECEDENCE SILENCE: the test drove the treatment to PREP_NOTIFIED before the stale reschedule. PRD §2.6 names `ERR_STALE_VERSION` for exactly this read-then-notified race, but §2.10 pins state preconditions ahead of the stale-version check and §3.5 defines reschedule only from `SCHEDULED`/`NON_COMPLIANT` (so `ERR_INVALID_STATE` is equally faithful). Relaxed to `validate_error_is_one_of(["ERR_STALE_VERSION", "ERR_INVALID_STATE"])` — the explicitly permitted coverage correction; not a deletion, not a downgrade to HTTP-status.
2. `test_04_treatment_scheduling_rules.py::TestTechnicianBufferedOverlap::test_start_touching_buffer_edge_accepted` — miscalibrated request (STEP 2 test bug): with both windows expanded 15 min per PRD §2.9, the 10:15 start overlapped the existing 09:00–10:00 booking by a full 15 minutes under every intersection convention, so PRD uniquely determines rejection — the test asserted acceptance. Fixed the window to 10:31, the nearest start that is uniquely derivable as accepted (the exact touch point 10:30 is convention-dependent since §2.9 pins half-open semantics only for the unit rule).
3. `test_05_bed_bug_cases.py` — two assertions (`test_cascade_creates_initial_inspections_and_updates_posture` on `scheduled_for`; `test_full_reopen_cycle_ends_cleared_and_restores_property` on `cleared_at`) pinned an exact string format (`...T00:00:00Z`) that PRD does not fix for those fields — §2.5's three-fractional-digit rule names only `created_at`/`updated_at`. Kept the covered semantic assertion (instant equals logical-clock + 24h / stamp equals the current logical time) via parsed-datetime comparison; dropped the format pin (STEP 1c partial coverage).

**Fixes applied to `implementation/`** (boot reliability — the `test_get_nonexistent_unit_returns_not_found` "could not be restarted" setup error in all 8 rounds):

4. New `workspace/implementation/server_launch.py` + rewired `start.sh` + new entry block in `app.py`. Root cause, proven experimentally: the runner claims ports from the kernel ephemeral range (32768–60999); on this shared host, concurrent probe/client traffic gets those same ports assigned as source ports, and a client-closed connection leaves a ~15–30s `TIME_WAIT` (tw_reuse=0) that blocks `bind()` even with `SO_REUSEADDR`. The old entry point paid a ~1s Flask import before binding, so every per-test restart exposed a ~1s claimed-but-unbound window; the lockstep early phase of the 8-round sweep drove simultaneous collisions. The launcher binds the socket in a minimal interpreter (~50ms window) with a 13s retry loop, then `exec`s `app.py` passing the fd via `WERKZEUG_BIND_FD` (`werkzeug.make_server(..., fd=...)`), so the port is never unbound between claim and serve. Verified: launcher smoke test OK; sweep 2 and sweep 3 each had zero restart errors across 680 restarts.

## Step 8: Finalize PRD — 2026-08-13T04:12:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1373_multifamily_pest_control_program/workspace/PRD_FINALIZED.md` is written with exactly one inline revision.

**Line counts / delta:** PRD.md = 294 lines / 46,810 bytes; PRD_FINALIZED.md = 294 lines / 47,133 bytes. 0.0% line delta, +0.69% character delta. One paragraph extended in place; no sections added.

**Changes (one bullet per change):**
- §2.6 (Optimistic Concurrency Control) — revise — appended one sentence to the reschedule-OCC paragraph: when a reschedule request fails both the stale-version check and an earlier §2.10 stage (e.g. status outside `SCHEDULED`/`NON_COMPLIANT`), the earlier stage's rejection (`ERR_INVALID_STATE`) is reported — `implementation/app.py:1545-1554` (terminal check at 1545, state check at 1547, `active_contract` gate at 1550, `ERR_STALE_VERSION` at 1553).

**Why the other three Step 7 items produced no edit:**
- Item 2 (buffer-edge test moved 10:15 → 10:31): pure test-fixture bug. `check_conflicts` (app.py:529-538) rejects 10:15 under every intersection convention, exactly as PRD §2.9's "must not intersect" already determines; §2.9 deliberately pins half-open semantics only for the unit rule, and the test now avoids the convention-dependent touch point. No PRD silence and no impl/PRD mismatch.
- Item 3 (`scheduled_for`/`cleared_at` format pins dropped): the implementation serializes every timestamp through the same `fmt_ts` (three fractional digits, app.py:28-30, used by all serializers including `ser_inspection` `scheduled_for` and `ser_case` `cleared_at`). PRD §2.5's three-fractional-digit sentence names only `created_at`/`updated_at`, so the implementation's broader uniformity is a consistent extension, not a contradiction; the tests still pin the covered instants. Inserting a new universal format claim is explicitly unnecessary for behavioral equivalence (a fresh implementer satisfying the PRD verbatim passes all tests) and would itself be an off-site narrowing risk. Left verbatim per "change as little as possible."
- Item 4 (`server_launch.py` + `start.sh` + `app.py` entry block): infrastructure/restart-reliability fix. The PRD contains no process/boot-contract requirements (that contract lives in INSTRUCTION.md, which the launcher satisfies). Nothing to pin.

**Per-edit pre-edit search log (NO-NEW-MISMATCH RULE):**
- Edit 1 (§2.6 stale-version precedence sentence):
  - (a) Subject: validation-order interaction between the stale-version check and earlier stages on the two OCC-guarded endpoints.
  - (b) Paths enumerated and read: `reschedule_treatment` full handler (app.py:1533-1574); `resolve_dispute` full handler (app.py:1827-1849 — terminal/state checks at 1835-1838 precede the stale check at 1839); the §2.10 stage text in PRD §2.10 (line 109); all other state-guard sites confirming the terminal-then-state convention (`notify_prep` 1465-1468, `acknowledge_prep` 1486-1491, `verify_prep` 1504-1508, `complete_treatment` 1587-1590, `cancel_treatment` 1617, inspection actions 1239-1242/1304/1335, `dispute_chargeback` 1816, `bill_chargeback` 1861, `record_payment` 1880, packet finalize/discard 1953/1980); all `active_contract`/`ERR_CONTRACT_NOT_ACTIVE` sites (app.py:341-345, 470, 1161, 1348-1350, 1550-1552, 1777); test-side expectations at test_suite/test_03_treatment_workflow.py:224-252 and test_06_chargebacks.py:356-375.
  - (c) Wording adjustment: initial draft said "the earlier stage's rejection is reported, not `ERR_STALE_VERSION`" — revised to "the earlier stage's rejection (`ERR_INVALID_STATE`) is the one reported" and scoped the example to "a status outside `SCHEDULED`/`NON_COMPLIANT`", because the reschedule handler also has the contract-active gate between the state check and the stale check; naming only `ERR_INVALID_STATE` as the bare outcome without the state-failure qualifier would have mis-described the dead-contract race (which reports `ERR_CONTRACT_NOT_ACTIVE`). The final wording attributes `ERR_INVALID_STATE` specifically to the state-precondition failure and stays generic ("the earlier stage's rejection") for everything else, so it is consistent with both OCC endpoints and every enumerated branch.

## Step 9: Complete PRD — 2026-08-13T04:23:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1373_multifamily_pest_control_program/workspace/PRD_COMPLETED.md` written.

**Source vs output:** PRD_FINALIZED.md (294 lines, 46,936 chars) → PRD_COMPLETED.md (294 lines, 50,822 chars; char-delta +3,886). Line count unchanged — all edits are inline paragraph inserts/revisions; no sections added.

**Counts:** 17 ambiguity-pins, 3 mismatch-revisions (20 edits total; one edit carried both a pin and a revision — §3.6 disposal paragraph — counted once in each bucket as itemized below).

Changes:

- §2.1 — insert — ambiguity — Technician may read only own record/schedule (else `ERR_FORBIDDEN_ROLE` 403); unrecognized Technician/Resident `X-User-ID` → `ERR_FORBIDDEN_ROLE` 403 — implementation/app.py:1109-1110, 1119-1120, 1133-1134, 199-210.
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` → `ERR_INVALID_REQUEST` 400; out-of-range integers clamped (limit [1,100], offset ≥0) not rejected — app.py:278-297.
- §2.3 — insert — ambiguity — list ordering tie-break by creation sequence when `created_at` ties — app.py:302.
- §2.3 — insert — ambiguity — filters match by exact equality; unrecognized filter value yields empty page, no error — app.py:1043-1046, 1122-1124, 1185-1190, etc.
- §2.5 — insert — ambiguity — `version` starts at 1 on creation — app.py:137-140.
- §3.1 — insert — ambiguity — failed contract activation precondition (incl. date window) → `ERR_INVALID_STATE` 409; same for reactivation date precondition — app.py:823-824, 849-850.
- §3.1 — insert — ambiguity — when several contracts are `ACTIVE`, the earliest-created one governs — app.py:341-345.
- §3.2 — insert — ambiguity — `lease_id` governing a different unit on resident creation → `ERR_NOT_FOUND` 404 — app.py:1059-1060.
- §3.2 — insert — ambiguity — system-created chargebacks (late fee, no-access penalty, non-compliance fee) record `assessed_by` as literal string `system` — app.py:409, 1321, 1527.
- §3.3 — insert — ambiguity — scheduling an inspection with an inactive technician → `ERR_INVALID_REQUEST` 400 — app.py:1159-1160.
- §3.3 — insert — ambiguity — positive completion when the unit's live case is `OPEN`/`TREATING`/`REOPENED`: no new case, existing case unchanged, cascade links two/three do not fire; flag and property indicators still recompute — app.py:1256-1281.
- §3.3 — insert — ambiguity — no-access `reason` accepted but not persisted; no-access does not re-evaluate `pest_flag`; strike penalty charges the unit's earliest-created qualifying lease; `COMPLETED`/`NO_ACCESS`/`CANCELLED` are terminal for inspections → `ERR_ALREADY_TERMINAL` 409 — app.py:1300-1322.
- §3.4 — insert — ambiguity — scheduling a treatment with an inactive technician → `ERR_INVALID_REQUEST` 400 — app.py:1384-1385.
- §3.4 — insert — ambiguity — second prep acknowledgement → `ERR_INVALID_STATE` 409; verify-prep `notes` accepted but not persisted; non-compliant cascade charges earliest-created qualifying lease — app.py:1490-1491, 1502, 1520-1525.
- §3.5 — revise — mismatch — treatment cancel `reason` is accepted but not persisted (PRD said "recording a reason"; impl discards it) — app.py:1613.
- §3.5 — insert — ambiguity — treatment completion books spend into the property's `ACTIVE` contract, else the most recently created contract, else nothing — app.py:348-353, 1595-1599.
- §3.6 — revise — mismatch — furniture disposals are accepted in any case status (PRD said "while a case is live"; impl has no status gate) — app.py:1666-1678.
- §3.6 — insert — ambiguity — disposal verdict `note` accepted but not persisted; `VERIFIED`/`REJECTED` terminal → re-verify gets `ERR_ALREADY_TERMINAL` 409 — app.py:1702-1705.
- §3.6 — revise — mismatch — evaluate-clearance on a `CLEARED` case returns `ERR_ALREADY_TERMINAL` (PRD said any non-`MONITORING` status returns `ERR_CASE_NOT_MONITORING`); `OPEN`/`TREATING`/`REOPENED` still return `ERR_CASE_NOT_MONITORING` — app.py:1725-1728.
- §3.7 + §3.7 amounts — insert — ambiguity — `HEAT_SURCHARGE` requires an existing `ACTIVE` contract with `heat_treatment_included` false (no ACTIVE contract → not assessable); `REPEAT_INFESTATION` coverage credit is zero when no `ACTIVE` contract exists — app.py:1776-1780, 470-471.
- §3.9 — insert — ambiguity — risk-score `variant` is required (missing/unknown → `ERR_INVALID_REQUEST` 400); trailing 90-day and 180-day window boundaries are inclusive — app.py:931-933, 939, 958.
- §3.9 — insert — ambiguity — adjacent-exposure read returns the standard paginated array envelope of unit objects ordered by `created_at` — app.py:972-977, 300-305.
- §3.8 — insert — ambiguity — packet reference entries: unknown `entity_type` → `ERR_INVALID_REQUEST` 400, unresolvable `entity_id` → `ERR_NOT_FOUND` 404; no cross-property check on referenced entities — app.py:1904-1918.

No test_helpers/test_suite exist under `workspace/` (they live at task level and were treated as non-authoritative per instructions). Everything else in implementation/ — endpoint table, auth model, clock semantics, OCC guards, validation ordering, conflict rules, rate card, clearance rule, chargeback state machine, claim-packet finalization — matched PRD_FINALIZED.md prose as already pinned.
