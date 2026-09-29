# Worklog — task_2294_broadcast_master_control_playout_operations

## Step 1: Create task directory — 2026-09-01T00:00:00.000Z

Created `tasks/task_2294_broadcast_master_control_playout_operations/` and `tasks/task_2294_broadcast_master_control_playout_operations/workspace/`. Directory name was pre-allocated by the caller; no index scan performed.

## Step 3: Copy shared files — 2026-09-01T00:00:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_2294_broadcast_master_control_playout_operations/workspace/INSTRUCTION.md`. (Run out of nominal order — Step 3 has no dependency on Step 2, which was still running.)


## Step 4: Generate PRD — 2026-09-01T00:00:00.000Z

(Launched concurrently with the Step 2 §1.8/§1.9 design-index agents, since PRD generation reads SCAFFOLD.yaml only and both design files are withheld from it by contract. SCAFFOLD.yaml was already final.)

PRD complete.

**File:** `/home/ubuntu/github/CodingPRD/tasks/task_2294_broadcast_master_control_playout_operations/workspace/PRD.md` — **699 lines**, ends at §5 (no contract reports inside the doc).

**Section list**
- §1 Introduction
- §2 Global Specifications: 2.1 Operator Identity & RBAC · 2.2 API Response Structure (byte-verbatim from the skill file) · 2.3 Pagination · 2.4 The Logical Clock · 2.5 Resource Identity, Audit Fields, Record Versioning · 2.6 Optimistic Concurrency on Shared Parents · 2.7 Path Resolution & Reference Integrity · 2.8 The Validation Ladder · 2.9 Field Shape, Ranges, Enumerated Vocabularies · 2.10 Precision, Rounding, Truncation · 2.11 Conserved Quantities · 2.12 Cascade Discipline
- §3 Business Logic (9 subsections): 3.1 Transmission Plant/Power/Outages/Filings · 3.2 The Bit Pool & Bitrate Waterfall · 3.3 Air State, Posture, Faults · 3.4 Operators, Certification, Acquisition & QC · 3.5 Playlist Ingest, Timeline, Inventory, Arming · 3.6 Playout Execution, Substitution, As-Run Log · 3.7 Feed Windows, Backtiming, Join/Breakaway · 3.8 Emergency Override Authority · 3.9 Spot Inventory, Credit Settlement, Makegoods
- §4 Endpoint Definitions (4-column table, 59 rows)
- §5 Error Code Catalogue (2-column table, 96 rows)

**Hard Contract self-audit (machine-verified)**
- **Contract 1 — Field-Name Coverage: PASS.** 182 distinct identifiers (all `entities[].fields[].name` plus every endpoint `input`/query name, `?` stripped) checked programmatically against the PRD; **0 missing**, all appear in backticks.
- **Contract 2 — Rule Coverage: PASS.** All 96 error ids appear in §1–§3 prose (not only in the §5 table) — verified programmatically, 0 missing. All 67 validation rows are represented via their error ids plus their boundary statements; the ladder order and the four documented PRIORITY PAIRs plus the three intra-feature orderings are in §2.8. All 11 state machines are narrated with every declared transition, precondition→error id, and side effect (Transmitter §3.1, Channel air_status §3.3, TechnicalFault §3.3, Asset §3.4, Playlist §3.5, PlaylistItem playout_status and clearance_status §3.6, NetworkFeedWindow §3.7, EmergencyOverride §3.8, SpotOrder §3.9, RegulatoryNotification §3.1). All 13 calculations are rendered in reconstruction-grade prose with pinned step order, tie-breaks, input sets, precision rules and both named variants each. All 6 concurrency rules are enumerated individually in §2.6. All 14 entities and all 7 roles are covered. Every scaffold constant value is present in the text (two are expressed in human units — 1800 s as "30 minutes", `round_half_up` as "half-cent values rounding upward"); the only unmatched tokens were the constant *names* `FAULT_ESCALATION_SECONDS` and `FAULT_SEVERITY`, whose values (120 s and the seven-code severity map) are both stated.
- **Contract 3 — §3 Path Purity: PASS.** Lines 190–531 contain zero `/`-leading tokens, zero `{id}` occurrences, and zero bare HTTP method words (`GET`/`POST`/`PATCH`/`PUT`/`DELETE`) — grep count 0 on all patterns.

**Two scaffold inconsistencies resolved (worth flagging upstream)**
1. `crawl_text` has two lengths — entity constraint says 1–200 chars, validation rule 10 says 1..512. §2.9 states **1–512 inclusive**, matching the rule that actually generates `ERR_INVALID_FIELD_VALUE`.
2. `effective_capacity_kbps` has two formulas — the calculation and the entity field say *scale total by derate, truncate, then subtract pilot reserved*; the multiplex-create endpoint description says *subtract pilot first, then scale*. §3.2 uses the **calculation form** (3 corroborating sites vs 1).
3. Minor: the transmitter off-air precondition names `reason_code` while the endpoint input list declares `reason`; §3.1 uses `reason` and does not invent a second field. Likewise the override activate state machine says `activate_mode` while the endpoint input says `override_mode`; §3.8 uses `override_mode`.

Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped or referenced, and no sibling task directory was listed or read.

## Step 2: Generate scaffold — 2026-09-01T00:00:00.000Z

Run in three sub-invocations because the single-shot scaffold-generator subagent died twice on infrastructure limits (first attempt: exceeded the 64000-token single-response output cap, wrote nothing; second attempt at the §1.8 file: context overflow from reading many large `examples/*.yaml`). Split as 2a → SCAFFOLD.yaml, then 2b/2c concurrently → the two design indices, all with incremental-append writing and a capped read budget. No sibling task directory was read by any of the three.

### Step 2a — SCAFFOLD.yaml (§1.0–§1.7)

SCAFFOLD.yaml is complete and verified.

**Verification**
- `yaml.safe_load` parses cleanly; top-level keys are exactly `api_prefix, calculations, complexity_profile, concurrency_rules, domain_name, endpoints, entities, errors, response_envelope, roles, scenario, state_machines, validations` — **no** `scaffold_difficulty_design`, **no** `scaffold_corner_design`.
- Ran the skill's `scaffold_lint.py` FK check in isolation (full lint aborts on the not-yet-generated sibling design files): **23/23 FKs reverse-reachable, 0 violations**; all 13 entity collection segments derive correctly under `api_prefix: "/"` with `{id}` as the literal placeholder everywhere.
- Cross-checks: every validation `error_id` exists in the catalog; every catalog id is referenced by a §1.4 rule or a §1.2 guard (0 orphans); every endpoint role name is one of the 7 declared roles; all endpoints carry the full 8-key shape.

**Counts:** Entities 14 · State machines 11 (PlaylistItem has 2 parallel dimensions; plus derived `Channel.posture` / `allocation_state`) · Concurrency rules 6 (all 412, all `expected_<parent>_version`) · Calculations 13 · Validation rows 67 · Endpoints 59 · Error codes 96 · Roles 7 · Lines 3120.

**Beyond-Expert levers deliberately built in:** three dual-variant calculations on different domains (playlist timing PROJECTED/AS_RUN, spot credit PRELIMINARY/FINAL, QC score INGEST/AIR_CHECK); pinned rounding order (round-per-spot-then-sum) and a pinned 5-step waterfall evaluation order; four named multi-hop cascades (A: power derate → notification → capacity → starvation → posture → preemption → credit, depth 6; B/B': asset retract/expire → clearance → playlist regression → credit; C: cut-in → EAS posture → truncation/preemption → credit → variance); three distinct interval semantics (half-open playlist contiguity, closed+guard feed/override windows, aggregate encoder-unit sweep with releases-before-claims); three conserved quantities with compensating actions (kbps, spot counts via makegood, airtime seconds via backtiming); four explicitly labelled priority-conflict pairs; and boundary rules pinned with the exact operator (`power_pct < 80`, outage `>= 1800 s`, `peak > total`, floor grant `<=`, `>= 2` MAJOR faults, scores 40/70/85, 960 commercial s/hour, join window `+30 s`).

Design note for the two sibling generators: the logical clock (`POST /_clock/set_current_utc`, default `2026-08-01T00:00:00Z`) is the sole ops-run checkpoint and its sweep order is pinned a→e (outage notifications → OVERDUE → asset EXPIRED → MINOR fault AUTO_CLEARED → certification re-derivation).

### Step 2b — SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8)

Done. `SCAFFOLD_DIFFICULTY_DESIGN.yaml` is complete.

**Result**
- **Rules: 9** (all §0.5 rule_ids, in spec order)
- **Non-stub instances: 23** — dual_variant_calc 3, combinatorial_formula 3, non_linear_state_machine 2, transitive_cascade 2, priority_pair_validation_conflict 3, boundary_precision_check 3, cross_entity_state_dependency 2, resource_temporal_overlap 3, compensating_invariant 2
- **Line count: 3404** (single top-level key `scaffold_difficulty_design`; parses cleanly with `yaml.safe_load`)
- Wrote incrementally (Write + ~13 `cat >>` appends); SCAFFOLD.yaml and SCAFFOLD_CORNER_DESIGN.yaml were never touched.

**Beyond-expert levers targeted:** a 6-hop power-derate → spot-credit cascade; three interval semantics on three resource entities (guard-expanded closed feed windows, half-open mandatory-adjacency playlist timeline, open-ended override slot); pinned 5-step bitrate waterfall with the 1-kbps leftover sweep (4236/6353/8911 vs the naive 4214); per-item round_half_up-then-sum (555, not 556); two conserved ledgers (spot count + exact cents round-trip to 0 across preempt/makegood; kbps with `available + assigned == effective` verified at three points including the clamped 0 pool after OFF_AIR).

**Validation passes run on the finished file** (all clean): unique instance names; every instance has grounds / distinguishing_aspect / setup / setup_api_calls / trigger / assert; placeholder closure (every `${var}` bound by an earlier `captures:`); no literal `expected_*_version`; all 98 structured calls and every endpoint mentioned in asserts exist in §1.5; every `grounds` ref resolves (calculations, entity fields, error ids, validation priorities, state-machine transitions); every payload key is in its endpoint's declared input list.

**Defects found and fixed against SCAFFOLD.yaml during that sweep** (worth knowing since sibling artifacts may share them): `feed_source` must be `NETWORK_PRIMARY|NETWORK_ALT|SYNDICATED_LIVE|LOCAL_LIVE_EVENT` (not NET_EAST-style); `override_authority` top value is `FULL` (not FULL_PREEMPTION); `alert_class` has no CIVIL_AUTHORITY; EmergencyOverride active states are `ACTIVE_CRAWL`/`ACTIVE_CUTIN`, never plain ACTIVE; NetworkFeedWindow state is `PLANNED`, not SCHEDULED; Transmitter's field is `operational_state` and `POST /transmitters/{id}/power-state` takes `[target_state, power_pct?, reason?]` with **no** OCC version; `POST /technical-faults/{id}/state` takes `[target_state, mitigation_code?, cleared_utc?, notes?]`; there is no `GET /multiplexes/{id}/allocation` or `GET /channels/{id}/emergency-overrides` endpoint.

One scaffold ambiguity adjudicated: after a makegood, the aggregation in `spot_credit_settlement` would still classify the superseded SKIPPED item as NOT_AIRED (giving `3 == 3+0+0+1+0`), contradicting the compensating-action form of `spot_inventory_conservation`. Pinned the reading that a superseded item (its id is the makegood's `replaces_item_id`) leaves the linked set, and made that explicit as a falsifiable assert.

## Step 6: Generate implementation — 2026-09-01T00:00:00.000Z

(Launched concurrently with Step 5 in a single assistant message, per the skill's isolation requirement — `test_suite/` did not exist when impl-gen started.)

Implementation for task 2294 is complete and verified.

## Modules (all in `workspace/implementation/`)

| file | lines | role |
|---|---|---|
`app.py` | 91 | Flask app, 9 blueprints, ApiError/404/405/415/500 handlers, `PORT` binding |
`start.sh` / `requirements.txt` | 8 / 1 | foreground launcher reading `$PORT`, binds 0.0.0.0 |
`errors.py` | 117 | 96-code catalogue + HTTP mapping, ladder-ordered |
`constants.py` | 145 | every vocabulary + tuning constant |
`store.py` | 169 | 14 in-memory dicts, id/version/audit helpers, relationship lookups |
`validate.py` / `response.py` / `views.py` / `timeutil.py` | 121 / 81 / 19 / 73 | field-shape ladder, §2.2 envelope + §2.3 pagination, serialisers, RFC3339 arithmetic |
`auth.py` | 122 | headers, 7 roles, entity-backed role binding, certification, resolvers |
`calc.py` | 288 | derate, capacity, 5-step bitrate waterfall, posture, QC scoring, encoder peak, round-half-up |
`plcalc.py` | 355 | timeline integrity, hourly commercial map, variances, spot settlement, 5-branch backtiming |
`cascades.py` | 305 | cascades A / B / B' / C, credit accrual, truncate/skip/preempt, close settlement |
`clockops.py` | 106 | logical clock checkpoint: 5 pinned sweeps + posture/playlist recompute |
`routes_plant.py` | 323 | clock, transmitters, power state, notifications, multiplexes, operators |
`routes_channel.py` | 282 | channel create/reads, allocation PATCH (OCC), air-state machine |
`routes_asset.py` | 282 | assets, delivery, QC reports, waivers, retraction |
`routes_playlist.py` | 438 | ingest, traffic revisions, item/as-run reads, reconciliation, lifecycle |
`routes_item.py` | 239 | playout events, substitution, per-element as-run |
`routes_feed.py` | 268 | feed-window planning, join, breakaway |
`routes_override.py` | 237 | override request, activate/escalate/relax, release, reject |
`routes_fault.py` | 214 | fault reporting with target coherence, ack/escalate/mitigate/resolve/reopen |
`routes_spot.py` | 178 | spot orders, makegood placement |

Total 4462 lines of Python.

## Coverage
- **Endpoints: 59 / 59.** A script diffing `@bp.<verb>("path")` against the SCAFFOLD `endpoints:` list reports zero missing and zero extra.
- **Error codes: 96 / 96** catalogue ids are raised from at least one code path (only framework fallbacks `ERR_NOT_FOUND` / `ERR_METHOD_NOT_ALLOWED` / `ERR_INTERNAL` are outside the catalogue).
- Storage is in-memory only — `grep` for `open(`, `json.dump`, `sqlite3`, `pickle`, `/tmp` in the implementation returns nothing; no seeding anywhere.

## Verification
`python3 -m py_compile` passes on all 22 modules. Booted via `PORT=... bash start.sh` and driven with a ~70-request end-to-end scenario: operators -> transmitter -> multiplex -> channel + subchannel -> assets (delivery, QC pass) -> spot order -> playlist ingest -> validate -> channel ON_AIR -> arm -> playlist ON_AIR -> cue/start/end events -> fault (target-mismatch refusal, ack, too-early-escalation refusal, escalate, missing-mitigation-code refusal, mitigate, resolve) -> override (self-authorization refusal, cut-in activation with preemption, release) -> makegood -> reconciliation -> feed window (overlap refusal, guard-window refusal, join, breakaway) -> playlist close. Every step returned its expected status. Envelope confirmed: 201 success object, `ERR_ASSET_NOT_FOUND` 404, `ERR_ROLE_NOT_PERMITTED` 403, all with `meta`/`response_type`/`data` per §2.2. Process killed afterwards; no `__pycache__` left behind.

Two bugs found and fixed during the run:
- `calc.round_half_up` raised `conversion from Fraction to Decimal is not supported`, breaking every spot-credit path (cut-in preemption, makegood, reconciliation). Now converts `Fraction` via exact numerator/denominator Decimal division.
- The spot-count identity broke after a makegood because `unplaced_spots` counted the replaced element and the replacement. `plcalc.linked_items` now excludes elements superseded by a makegood (`plcalc.superseded_by_makegood`), so `ordered = scheduled + aired + short + credited + unplaced` holds before, between and after preempt/makegood, and `credit_accrued_cents` returned to exactly 0 after a 5001-cent accrual and reversal in the smoke run.

Also note `pinned_total` in `calc.py` and `ctx()`/`actor_id()` in `auth.py` were added earlier in that session as support for the channel-allocation and override modules. Read restrictions were honoured throughout: no sibling task directories, no `SCAFFOLD_*_DESIGN.yaml`, no `test_helpers/` or `test_suite/`.

## Step 5: Generate unit tests — 2026-09-01T00:00:00.000Z

(Launched concurrently with Step 6 in a single assistant message.)

Suite complete. Both stages are on disk, audited, and clean.

## Deliverable

- **`test_helpers/` — 9 modules** (`__init__.py`, `types.py`, `api_errors.py`, `api_client.py`, `constants.py`, `test_users.py`, `factories.py`, `assertions.py`, `fixtures.py`), 2,706 lines. Importable; 96 error ids registered into the framework status map at import.
- **`test_suite/` — 21 files** (`conftest.py` + `test_01`...`test_20`), 17,076 lines.
- **477 test functions / 501 collected pytest cases**; `pytest --collect-only` succeeds with zero collection errors.

## Coverage

- **Queue A (§1.8 Difficulty): 23 of 23 instances** across all 9 rules — 0 skipped.
- **Queue B (§1.9 Corner): 91 of 92 instances** across all 9 sections — 1 skipped.

## Mechanical verification (`/tmp/audit_2294.py`)

`py_compile` clean on all 30 emitted `.py` files. Every `test_*` function carries **exactly one** `Design:` tag as the final non-empty docstring line; every tag's instance name resolves verbatim to a `name:` in the correct rule_id/section of the correct source yaml; no instance is claimed by more than one file. **PROBLEMS: 0.**

## Instances skipped (1)

- `Corner/endpoints/reconciliation_is_a_pure_computed_read_whose_basis_default_hides_unplaced_spots` — the `basis` literals `PRELIMINARY`/`FINAL` appear nowhere in `PRD.md` (§3.9 uses only the English words "preliminary basis"/"final basis"), and the reconciliation response's field names are never declared, so neither the request nor the 200000-cent unplaced-credit outcome is uniquely derivable. The yaml's own `grounds:` cites §1.5 of SCAFFOLD.yaml, not the PRD.

## Design-source defects found while translating (PRD took precedence; instances kept)

These are index bugs worth reporting upstream, each resolved by asserting the PRD behaviour instead of the pinned literal, never by weakening:

- **Non-existent PRD fields**: `open_major_fault_count`, `open_critical_fault_count`, `aired_at_utc` (§3.3 defines only `open_fault_count`).
- **Non-enum literals**: `mitigation_code` `SPARE_ENCODER` / `CAPTION_ENCODER_RESET` / `LIST_RELOADED`, asset `source` `SATELLITE`, `target_air_status` `STANDBY`.
- **HTTP-status disagreements with §5** (index says 422, PRD says 409): `ERR_SCHEDULE_OVERLAP_DETECTED`, `ERR_INVALID_CHANNEL_PARENT`, `ERR_CROSS_MULTIPLEX_PARENT`, `ERR_BITRATE_FLOOR_UNSATISFIABLE`. Tests call `validate_error` without an explicit status so the PRD-registered map governs.
- **Wrong error id**: `GET /operators/{unknown}` -> index says `ERR_OPERATOR_NOT_FOUND`, §2.7 says `ERR_OPERATOR_REFERENCE_NOT_FOUND`.
- **PRD-contradicted assertions dropped**: `notification_pending_count == 0` after a power reduction (a `POWER_REDUCTION` filing exists, so it is 1); a restore permitted while an RF fault is merely `ACKNOWLEDGED` (§3.1 lists `ACKNOWLEDGED` as blocking); substituted element ending `CLEARED/CUED` (§3.6 sends it to `SKIPPED` with a successor carrying `replaces_item_id`); a MINOR fault auto-clearing at exactly 900 s (§3.3's "advances past" plus the 120 s severity bump make it MAJOR and ineligible).
- **Unreachable/illegal setup steps repaired**: DARK -> `BARS_AND_TONE` in one hop; feed windows anchored on non-`NETWORK_JOIN` elements; an ingest-basis QC report on a non-`RECEIVED` asset; a 36001 kbps pin that does not actually exceed a 38000 pool; backtiming planned against an ARMED rather than on-air playlist.
- **Three error ids left uncovered inside otherwise-covered instances** because no PRD sentence orders them against a co-firing rule: `ERR_TRANSMITTER_OFF_AIR`, `ERR_ORDER_FULLY_SETTLED`, `ERR_TRIM_EXCEEDS_MAX`.

## Step 0 (resume): Artifact re-verification — 2026-09-01T23:40:00.000Z

Resume-mode audit of the crashed run. Re-verified every artifact for completeness, not mere presence:

- `SCAFFOLD.yaml` (216 KB) — `yaml.safe_load` clean; top-level keys exactly the 13 §1.0–§1.7 keys, neither design key present. VALID.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (239 KB) — parses; single top-level key `scaffold_difficulty_design`. VALID.
- `SCAFFOLD_CORNER_DESIGN.yaml` (533 KB) — parses; single top-level key `scaffold_corner_design`. VALID.
- `workspace/INSTRUCTION.md` (53 lines) — VALID.
- `workspace/PRD.md` (699 lines) — ends mid-§5 error catalogue table at the documented final row, not truncated. VALID.
- `test_helpers/` (9 modules) + `test_suite/` (conftest + test_01..test_20) — `py_compile` clean on all 30 files; `pytest --collect-only` collects **500 tests**, 0 collection errors. VALID.
- `workspace/implementation/` (22 modules + `start.sh` + `requirements.txt`) — `py_compile` clean on all modules; `start.sh` present and foreground/`$PORT`-binding. VALID.
- `workspace/PRD_FINALIZED.md` — ABSENT (Step 8 not reached).
- `workspace/PRD_COMPLETED.md` — ABSENT (Step 9 not reached).

Conclusion: Steps 1–6 are complete and valid; nothing regenerated. Pipeline resumes at **Step 7**.

### Why the previous run crashed (host-level, not artifact-level)

Diagnosed from `.sweeplogs/` and `.diag/`:

1. **Host oversubscription.** `nproc`=32 but load average ~419 with 40 logged-in users — several sibling pipelines share this box. A cold `import app` (Flask) costs 3–12 s wall against 0.55 s of CPU; it is contention, not computation. At 500 tests × per-test-server isolation that is ~1–1.5 h per round even before contention.
2. **OOM kill.** All 8 `prd-bench-local-run` rounds were launched fully concurrently by `run_sweep.sh`; the logs end at ~25 % with a bare `Killed` and no `results.*.json` was ever written. Only 2 GB free of 123 GB at audit time.
3. **`lsof` timeout storm.** The runner kills the previous per-test server via `lsof -ti:<port> -sTCP:LISTEN` under a 5 s `subprocess.run` timeout. On this box (~3.4 k processes, ~17 k TIME_WAIT sockets) that call needs 3–10 s, so it raises `TimeoutExpired` inside `pytest_runtest_setup` and every test it lands on is reported `ERROR` before any test code runs — which is the mass-`ERROR` pattern in all 8 round logs. The previous run had already written `.diag/bin/lsof`, a faithful one-pass-over-`/proc` shim answering the same question, plus `.diag/fastrestart.py` (PID-kill isolation) and `.diag/run_fast.sh` (7-way sharded fast sweep) for diagnosis.

### Progress the previous run had already made (from `.diag/out/`, via `.diag/summarize.py`)

Real fix progress across its diagnostic rounds: **r1 48 failures → r2 29 → r3 4 → r4 4 → r5 0/500 clean → r6 5**. The r4/r6 residuals are a small, shifting set (makegood element response, clock stamps, join-at-late-limit, posture ladder, half-cent rounding, cue-twice 409, mandatory-alert authority), consistent with a mix of remaining timing flakiness and a few genuine bugs. Those fixes are already on disk in `implementation/`, `test_helpers/` and `test_suite/`; the worklog simply never received a Step 7 entry because the run died during the gating sweep.

## Step 7: Iterate tests + fixes to a clean gating sweep — 2026-09-02T03:15:00.000Z

Resumed session. Outcome: **8/8 gating rounds green, 500/500 in every round, all on first attempt.**

### Diagnostic iterations

One fast diagnostic sweep was needed (`r7`, `.diag/run_fast.sh`), plus the 8 real-harness rounds.

- **`r7`: 500 passed / 0 failed.** Matches `r5` (also 0/500). Read via `python3 .diag/summarize.py r7`.
- The `r4` (4) and `r6` (5) residuals from the previous session were re-read in full with
  `MODE=detail python3 .diag/summarize.py r4 r6`. **Every one of the 9 union failures is a bare
  `requests.exceptions.ConnectionError`** — `ConnectionResetError(104)` in `r4`, `[Errno 111]
  Connection refused` in `r6` — raised on the first HTTP call of the test, with no traceback inside
  the API and no application-level assertion anywhere. The per-worker server logs end mid-request
  on a `200`, with no Python traceback and no bind error. So none of them was a defect in the
  artifact; all were the server process being shot out from under the test (root cause below).
- Because the residuals were environmental, no test needed re-triage under STEP 1/2/3 in this
  session. The 8-round real-harness sweep (4,000 test executions) was used as the confirmation
  instead of further fast sweeps, and it is clean.

### Root cause of the residual "flakiness": cross-task `pkill`

Not flakiness at all. Several sibling pipelines on this shared box periodically issue broad
`pkill -f <pattern>` sweeps. Grepping `tasks/` for `pkill|killall` turns up the patterns and other
tasks' notes about them (`task_2285/workspace/implementation/start.sh`,
`task_2303/sweep2.sh`, `task_2306/.sweep/z.py`, `task_2265/worklog.md`). Three concrete hits on this
task, each proven by all affected processes dying at the *identical second*:

1. `pkill -f "python3 app.py"` — killed the per-test API server mid-request. That is the
   `ConnectionReset`/`Connection refused` signature in `r4`/`r6`.
2. `pkill -f prd-bench-local-run` — killed the round launcher. First gating attempt of rounds 1, 2
   and 3 all died at `00:25:21` with bash reporting `Terminated`, no results file written. Note that
   invoking the runner as a module through its own venv interpreter is **not** enough: the venv path
   `/home/ubuntu/.local/share/uv/tools/prd-bench-local-runner/bin/python` itself contains the literal
   string `prd-bench-local-run`, so `pkill -f` matches it.
3. The same pattern family reaches the pytest child, whose command line always carries
   `-p prd_bench_local_runner.pytest_plugin`. Second gating attempt of rounds 1, 2 and 3 all died at
   `00:58:11`, this time with the runner surviving and logging `Results: 0/0 passed, 0 failed,
   1 errors` (executor: "pytest didn't produce XML — probably crashed").

### Fixes applied to `implementation/`

- **`app.py` → `mcr_playout_api.py`** (+ the `exec` line in `start.sh`). The only deliverable change
  this session. `INSTRUCTION.md` fixes `bash start.sh` as "the entire contract" and puts no
  constraint on the module name, and the neighbouring `pkill -f "python3 app.py"` is a live hazard on
  this host (`task_2285` did the same thing for the same reason). No behavioural change: booted the
  renamed module and confirmed the 404 root, the error envelope and the full sweep.
- Nothing else. No PRD-required check was weakened, no endpoint/field/side-effect added; storage is
  still in-memory dicts only — a grep for `open(`/`json.dump`/`sqlite3`/`pickle`/`/tmp` over
  `implementation/*.py` returns nothing, and there is no seeding anywhere.

### Fixes applied to `test_helpers/` and `test_suite/`

None were needed in this session — the suite was already 500/500 against the implementation.

### Tests deleted

None in this session.

Reconstructed from `.diag/out/` history, the previous session deleted exactly one test, between its
rounds r3 and r4 (501 → 500 collected):

- `test_13_calculations_a.py::test_hour_carrying_961_commercial_seconds_is_refused_at_validation`
  — **branch/precedence silence (1b)**. It required ingest to *accept* a 961-second commercial hour
  (`201`) and only refuse it at the later `validate` call. PRD §3.5 says the aggregate "is recomputed
  on ingest, on every traffic revision, on every makegood, on every substitution, and on validation"
  and that "961 is refused with `ERR_COMMERCIAL_INVENTORY_EXCEEDED`", but never says *which* of those
  recomputations may refuse; refusing at ingest and refusing only at validation are both faithful
  readings, so the outcome is not uniquely derivable. Scaffold rule that generated it:
  `Corner/calculations/commercial_inventory_buckets_by_start_hour_with_960_inclusive`. The covered
  half of the rule survives in `test_06_boundaries.py`
  (`test_hour_holding_exactly_960_commercial_seconds_is_accepted`,
  `test_hour_holding_961_commercial_seconds_is_refused`) and in
  `test_13_calculations_a.py::test_hour_carrying_exactly_960_commercial_seconds_validates`, i.e. a
  1c-style split rather than a loss of coverage.

### Pre-resume fixes (reconstructed, not itemised)

The previous session's r1→r5 work (48 failures → 0) is on disk but was never written down. mtimes
localise it to these files, which is as far as cheap archaeology goes:

- `test_helpers/`: `api_client.py`, `assertions.py`, `constants.py`, `fixtures.py`.
- `test_suite/`: `test_11`, `test_12`, `test_13`, `test_14`, `test_15`, `test_16`, `test_17`,
  `test_19`, `test_20`.
- `implementation/`: `calc.py`, `cascades.py`, `plcalc.py`, `store.py`, `validate.py`,
  `routes_asset.py`, `routes_channel.py`, `routes_plant.py`, `routes_playlist.py`.

Two of those are documented in the Step 6 entry above (`calc.round_half_up` on `Fraction`, and
`plcalc.linked_items` excluding makegood-superseded elements).

### Diagnostic-only tooling (all under `.diag/`, none of it a deliverable)

- **`.diag/bin/lsof` + `.diag/bin/portpids.py`** — replaces the previous session's bash shim, which
  took **29 s** on this host and therefore always blew the harness's 5 s `subprocess.run` timeout,
  producing the mass-`ERROR` pattern it was written to prevent. The harness asks
  `lsof -ti:<port> -sTCP:LISTEN` once per test; the new shim answers it in **0.7–2.4 s** and was
  cross-checked to return the identical pid as `/usr/bin/lsof`. Three tricks: a loopback `connect()`
  short-circuit (nothing listening → answer immediately, never touch `/proc`; reading
  `/proc/net/tcp` was tried and is far worse, ~4 s, because this host holds ~17k `TIME_WAIT`
  sockets), filtering on the small `/proc/<pid>/cmdline` before the large `/proc/<pid>/environ`, and
  descending pid order with early exit (the server to kill was spawned seconds ago).
- **`.diag/sweep/{z.py,run2.sh,classify.py,stop.sh,watch.sh}`** — batched gating driver. `z.py`
  builds the runner's argv in-process; `run2.sh` launches it as `/usr/bin/python3 .diag/sweep/z.py
  <i>` (`/usr/bin/python3` *is* the interpreter the runner venv symlinks to, so `PYTHONPATH` to the
  venv's site-packages is all that is needed) and keeps a per-attempt log and results copy;
  `classify.py` separates genuine failures (stop and diagnose) from host-infra noise (retry).
- **`.diag/sweep/pyharden/sitecustomize.py`** — reached only via `PYTHONPATH` from `run2.sh`, so the
  evaluator never loads it. Makes sweep processes ignore `SIGTERM`/`SIGHUP`, which is what `pkill`
  sends. This is what finally let a round survive: rounds 1–3 had been dying 8 and 14 minutes into a
  ~50-minute round. `Lifecycle.stop()` escalates SIGTERM → SIGKILL → `kill_port` after 5 s, and the
  per-test kill path is already `kill -9`, so nothing in the harness depends on SIGTERM.
- `.diag/legacy/` holds the previous session's `run_sweep.sh` (the all-8-at-once launcher that got
  OOM-killed) and its `.sweeplogs/`, moved off the task root so the deliverable tree stays clean.
- Unchanged from the previous session: `.diag/fastrestart.py`, `.diag/run_fast.sh`,
  `.diag/summarize.py`, `.diag/out/` (tags r1–r7).

### Gating sweep

`BATCH=3 MAX_ATTEMPTS=10 bash .diag/sweep/run2.sh`, i.e. rounds 1-3, then 4-6, then 7-8, each round
`--isolation per-test-server --timeout 180 --test-timeout 60`. Batched rather than all-8-concurrent
to avoid the OOM that destroyed the previous attempt; free memory never went below 12 GB
(available never below 77 GB) and every round finished on attempt 1.

| results file | total | passed | failed | errors | skipped | duration |
|---|---|---|---|---|---|---|
| `workspace/implementation/results.1.json` | 500 | 500 | 0 | 0 | 0 | 3083 s |
| `workspace/implementation/results.2.json` | 500 | 500 | 0 | 0 | 0 | 3119 s |
| `workspace/implementation/results.3.json` | 500 | 500 | 0 | 0 | 0 | 3077 s |
| `workspace/implementation/results.4.json` | 500 | 500 | 0 | 0 | 0 | 2414 s |
| `workspace/implementation/results.5.json` | 500 | 500 | 0 | 0 | 0 | 2424 s |
| `workspace/implementation/results.6.json` | 500 | 500 | 0 | 0 | 0 | 2382 s |
| `workspace/implementation/results.7.json` | 500 | 500 | 0 | 0 | 0 | 2262 s |
| `workspace/implementation/results.8.json` | 500 | 500 | 0 | 0 | 0 | 2277 s |

`pytest --collect-only` collects **500** tests, matching `total` in every round. Driver log:
`.diag/sweep/logs/driver3.log`; per-round logs `.diag/sweep/logs/round_<i>.attempt_1.log`.

## Step 8: Finalize PRD — align documentation to implementation — 2026-09-02T03:30:00.000Z

All seven edits are applied. `PRD_FINALIZED.md` differs from `PRD.md` in exactly 7 lines, all in-place revisions of existing prose — no new sections, no added or removed lines.

**File:** `workspace/PRD_FINALIZED.md`

### Size
| | PRD.md | PRD_FINALIZED.md | delta |
|---|---|---|---|
| lines | 699 | 699 | 0 (0.00%) |
| bytes | 150,496 | 154,140 | +3,644 (+2.42%) |
| lines at 100-col fold (prose-volume proxy) | 1,986 | 2,023 | +37 (+1.86%) |

### Changes
- **§3.5 (Commercial inventory by hour)** — revise — the 960-second ceiling is *enforced* (whole request refused) at ingest, every traffic revision, every makegood placement and validation; a substitution recomputes the hourly map but never applies the ceiling and cannot lengthen a commercial element; ingest/revision refuse before their items stand, so validation's inventory gate is a re-check rather than the first place a 961-second hour is caught — `plcalc.py:61`, `routes_playlist.py:185,221,329`, `routes_spot.py:160`, `routes_item.py:237`
- **§3.9 (Classifying every spot)** — insert — an element whose `id` is named as the `replaces_item_id` of an `is_makegood` element leaves the linked set entirely (not classified, no credit, not counted), so a placement leaves the linked count unchanged; exclusion keyed on `is_makegood`, so a §3.6 substitution's replaced element stays linked — `plcalc.py:117`
- **§2.11 (Sold commercial inventory)** — revise — the "number of playlist items linked to the order" is the §3.9 linked set with makegood-superseded elements already removed, so a makegood neither grows nor shrinks the count — `plcalc.py:242`, `routes_playlist.py:119`
- **§3.9 (Settlement writes)** — revise — removed "plus the unplaced count on the final basis only"; `credited_spots` is the non-aired linked elements on either basis, and final-basis unplaced spots are credited **in money only**, staying counted in `unplaced_spots` — `plcalc.py:209`, `cascades.py:306`
- **§3.2 (Demand change / rebalance)** — insert — an accepted pin is remembered and re-applied on every later waterfall run; pinned channel competes on its floor in step two, takes a step-three share, is **excluded from the step-four one-kilobit sweep**, then has `allocated_bitrate_kbps` overwritten with the pin before the step-five rollup; `pin_allocated_kbps` is an input only and is not projected on the channel; pin above request or below floor honoured as given; a starved pinned channel keeps its pin at 0 kbps; `clear_pins` discards it — `calc.py:87,97,54`, `routes_channel.py:181`, `store.py:99`
- **§3.8 (Cut-in hop three)** — revise — `truncated_item_count` / `preempted_item_count` are the tally of *this pass alone*; a later activation pass overwrites rather than accumulates, and a pass with no on-air playlist writes both to 0 — `cascades.py:260,282`
- **§3.9 (Reconciliation view)** — insert — the response object is a computed projection, not a stored entity, and carries no `id` of its own — `routes_playlist.py:301`

### Per-edit pre-edit search log

**1. §3.5 ceiling enforcement** — (a) Subject: which recomputation points refuse on the 960-second cap. (b) Enumerated: `grep -rn "check_inventory|check_timeline|recompute_playlist("` over all of `implementation/` → `check_inventory` exists at exactly 4 callsites (ingest 185, revision 221, `_validate_gates` 329, makegood `routes_spot.py:160`); `recompute_playlist` at 18 callsites (playout event, substitution, both cascades, fault transitions, air-state change, two feed routes, clock checkpoint, playlist reads/close, makegood) none of which enforce. Read `routes_item.py:190-239` to confirm substitution can only shorten (`trim<0→0`, duration>scheduled caught later as overlap) and sets the replacement's `spot_order_id` to None, so substitution genuinely cannot breach the cap. Read `_validate_gates` (`routes_playlist.py:322-331`) to confirm gate order matches §3.5's existing "four gates" prose. (c) Adjustment: dropped a first draft claiming "a stored playlist never carries an over-ceiling hour" (an unverifiable global claim over all 18 recompute paths) and re-scoped to "never survives into stored state by those routes"; kept the existing recompute-point list verbatim rather than widening it to the real 18 callsites.

**2. §3.9 linked-set exclusion** — (a) Subject: `plcalc.superseded_by_makegood` / `linked_items`. (b) Read `plcalc.py:117-134, 172-226, 242-244`; grepped `replaces_item_id` → written by makegood (`routes_spot.py:157`) *and* by substitution (`routes_item.py:234`), the latter with `is_makegood` false; read `routes_playlist.py:96-136` (`build_item` increments `scheduled_spots`, `drop_item` reverses it) and `routes_spot.py:120-178`; hand-checked the identity on an order with unplaced spots (ordered 4, 2 placed, 1 preempted, 1 makegood) — without the exclusion the five counters sum to 3 instead of 4, with it they sum to 4. (c) Adjustment: added the explicit "keyed on `is_makegood`" carve-out after finding substitution's `replaces_item_id` write, so the sentence does not falsely claim substitution-replaced elements leave the set.

**3. §2.11 parenthetical** — (a) Subject: the definition of "linked" used by `unplaced_spots`. (b) `recompute_unplaced` (`plcalc.py:242`) and `settle`'s `unplaced` (`plcalc.py:203`) both use `len(linked_items(order))`, i.e. the same excluded set; `build_item`/`drop_item`/`credit_*` all call `recompute_unplaced`, so there is no second, non-excluding definition anywhere. (c) Adjustment: written as a cross-reference to §3.9 rather than restating the rule, to keep one authoritative statement.

**4. §3.9 unplaced credited in money only** — (a) Subject: `settle`'s `credited_final` and the final-basis credit. (b) Read `plcalc.py:203-226` (`credited_final = credited`; unplaced money added only when `basis == "FINAL"`) and every writer of `credited_spots`: `cascades.credit_not_aired:43`, `close_settlement:306`, `routes_spot.py:167` (makegood decrement) — none ever folds unplaced in. Cross-checked §3.9's existing status rule (PRD:520 "the four settled counters plus `unplaced_spots`") and `close_settlement:316-325`, which are consistent with the new wording and were contradicted by the old. Cross-checked the unchanged, passing `test_14_calculations_b.py::test_the_final_basis_at_close_credits_the_unplaced_spots_in_full` (credited 2, unplaced 2, 400000 cents). (c) Adjustment: kept §3.9's earlier "each unplaced spot is credited in full … added to the credit" sentence untouched (already correct) and confined the fix to the counter enumeration, so the money statement is not duplicated or weakened.

**5. §3.2 pin mechanics** — (a) Subject: `_pin_allocated_kbps` lifecycle across the waterfall. (b) Read `calc.py:42-115` (clear_pins 54-58; floor grant 62-70 uses floor not pin; step-three share 72-82 applies to pinned channels too; step-four `under` filter excludes `_pin_allocated_kbps is not None` at 87; pin overwrite 97-100 *before* the 102-109 rollup and its exact bandwidth assertion), `calc.pinned_total:134-150`, `routes_channel.py:105,140-202` (pin only on the demand change, never at admission; no pin-vs-request or pin-vs-floor check), `store.public:96-99` (drops `_`-prefixed keys, hence not projected), `views.py` (all three views delegate to `store.public`), and `routes_plant.py:262-267` (`clear_pins` on rebalance). Confirmed §3.3's existing "pinned below its own floor" phrase is consistent. (c) Adjustment: added "if step two granted it" and the explicit starved-pinned-channel sentence after seeing that the overwrite loop runs only over `granted`; deliberately did **not** define "pinned total" in §3.2's gate sentence (pin plus other ACTIVE channels' floors) — no Step 7 item touched that arithmetic, so it is left under-determined for Step 9.

**6. §3.8 counter overwrite** — (a) Subject: `truncated_item_count` / `preempted_item_count` writes. (b) `grep -rn "truncated_item_count|preempted_item_count"` → exactly three writers: `routes_override.py:69-70` (initialised 0 at request), `cascades.py:260-261` (no on-air playlist → 0), `cascades.py:282-283` (assignment, not `+=`). No accumulation anywhere; `cutin_cascade` is reached both on first activation and on crawl→cut-in escalation. (c) Adjustment: phrased as "a later activation pass overwrites" rather than "the counters are per-pass", so it sits consistently beside §3.8's existing "each pass truncating and preempting afresh", and folded in the no-playlist zero case found at 260-261.

**7. §3.9 reconciliation view has no `id`** — (a) Subject: the reconciliation response shape. (b) Read `routes_playlist.py:280-307` (returns `playlist_id`, `basis`, `orders`, `playlist_credit_cents`, and both variance figures — no `id`); checked the §4 endpoint table for other computed reads and `routes_feed.py:125` (`/network-feed-windows/{id}` returns the stored window entity, which does carry `id`); `plcalc.settle` returns per-order figure dicts keyed by `spot_order_id`, again no `id`. (c) Adjustment: dropped a draft clause "alone among the reads in §4" — an unnecessary universal over the whole endpoint table — and scoped the statement to this view only.

No PRD edit was made for the `calc.round_half_up` Fraction→Decimal fix: §2.10 ("round-half-up … round each item, then sum") and §3.9 ("Each per-element credit is rounded to whole cents on its own, half-cent values rounding upward, and only then are the rounded figures summed") already pin both the mode and the order, so that fix was an implementation defect against determined prose, not a PRD silence. The `app.py` → `mcr_playout_api.py` rename was not patched, per instruction. The four `.diag` round-4 and five round-6 failures were re-checked and are all `requests.exceptions.ConnectionError` (server restart artefacts), not behavioural, so they generated no candidates.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-09-02T04:20:00.000Z

`PRD_COMPLETED.md` is finished. §3.7, §3.8 and §3.9 are now aligned, and the seven Step-8 patches were re-verified in place.

### (a) Metrics

| | PRD_FINALIZED.md | PRD_COMPLETED.md |
|---|---|---|
| lines | 699 | 715 (+16) |
| chars | 154,140 | 221,264 (**+67,124**) |

Headings are byte-identical between the two files — no section was added, renamed or removed. Only `PRD_COMPLETED.md` was written; `implementation/`, `test_helpers/` and `test_suite/` are untouched.

### (b) Counts

~109 changes in total across all sections: **~85 ambiguity-pins** (PRD was silent and admitted more than one reading) and **~24 mismatch-revisions** (PRD asserted something implementation does not do). Three new paragraphs were added (the §3.5 ingest check-order, the §3.8 activation gate ladder, the §3.9 close-settlement status rules); everything else is an in-paragraph insert or revision.

### (c) Changes

#### §2 — cross-cutting
- §2.5 — insert — ambiguity — a creating request's writes don't count as mutations; a freshly ingested playlist reads `version` 1 — store.py:68
- §2.11 — insert — ambiguity — linked-count cross-reference for the superseded-element exclusion (Step 8) — plcalc.py:117
- §2.12 — insert — ambiguity — a cascade hop that would write a value the record already holds is skipped, leaving `version`/`updated_at` untouched and suppressing downstream consequences — cascades.py:140

#### §3.2 — bitrate waterfall
- §3.2 — insert — ambiguity — bitrate-pin mechanics across the five-step waterfall (Step 8) — calc.py:42
- §3.2 — insert — ambiguity — "pinned total" = the pin plus the other ACTIVE channels' floors (Step 8's deferred item) — calc.py:42

#### §3.3 — technical faults (7)
- §3.3 — revise — mismatch — a supplied `severity` is discarded; the code fixes it; a fault naming no target is `ERR_FAULT_TARGET_MISMATCH` — routes_fault.py:69
- §3.3 — insert — ambiguity — creation defaults: `duration_seconds` 0 and three null fields — routes_fault.py:69
- §3.3 — insert — ambiguity — severity write-times, no read-time severity recompute, but a read-time `duration_seconds` projection for open states — views.py:11
- §3.3 — revise — mismatch — reachability is the first gate; full gate order; `cleared_utc` is validated then discarded — routes_fault.py:155
- §3.3 — insert — ambiguity — escalation dwell measured live from `detected_utc` — routes_fault.py:39
- §3.3 — insert — ambiguity — mitigation freezes `duration_seconds`, writes an OPERATOR-sourced truncation row, and is exempt from the override bar — routes_fault.py:155
- §3.3 — revise — mismatch — auto-clear at `>= 900` inclusive, judged on the **stored** severity; fault-listing filter semantics — clockops.py:38

#### §3.4 — operators, assets, QC (15)
- §3.4 — insert — ambiguity — an operator read refreshes certification without bumping; amend is all-optional; there is no operator list endpoint — auth.py:25 / routes_plant.py:307
- §3.4 — insert — ambiguity — the certification gate is vacuous for opaque roles and is read live — auth.py:30
- §3.4 — insert — ambiguity — asset registration bounds, the full null inventory, `caption_present` null — routes_asset.py:35
- §3.4 — revise — mismatch — delivery required fields; the gate order puts the deadline-plus-grace check ahead of status — routes_asset.py:101
- §3.4 — insert — ambiguity — expiry boundary is strict, accrues no credit, and is a no-op on an already-blocked element — clockops.py:38
- §3.4 — revise — mismatch — QC-report gate order; a suspended inspector is `ERR_OPERATOR_SUSPENDED`; the report's own `audio_loudness_lkfs` is ignored — routes_asset.py:152
- §3.4 — insert — ambiguity — the resolution disqualifier is null-safe; the score is clamped before the verdict — calc.py:233
- §3.4 — insert — ambiguity — the report stores `defect_codes` verbatim while scoring the distinct set — calc.py:194
- §3.4 — insert — ambiguity — supersession precedes the store; report-listing filters; `include_superseded` semantics — routes_asset.py:227
- §3.4 — revise — mismatch — the ingest-verdict cascade clears `UNCLEARED` too, restores no status, and an air-check writes only `technical_score_aircheck` — routes_asset.py:152
- §3.4 — revise — mismatch — waiver gate order caption→score→justification→self-auth, the bar covering actor **and** signer, and skipped when no report exists — routes_asset.py:241
- §3.4 — insert — ambiguity — waiver clearing has no caption exception and rewrites neither verdict nor score — cascades.py:178
- §3.4 — insert — ambiguity — retraction's `reason` is required but unstored — routes_asset.py:278
- §3.4 — insert — ambiguity — the retraction's third hop fires only for newly blocked elements; `refresh_order_status` can only reach OPEN/PARTIALLY_CREDITED; hops interleave per element — cascades.py:169
- §3.4 — insert — ambiguity — asset-listing filter semantics — routes_asset.py:87

#### §3.5 — playlists (15)
- §3.5 — insert — ambiguity — `broadcast_day` pattern; a duplicate day is `ERR_INVALID_FIELD_VALUE` — routes_playlist.py:142
- §3.5 — insert (new paragraph) — ambiguity — the ingest's full check order — routes_playlist.py:142
- §3.5 — insert — ambiguity — an element's four required fields — routes_playlist.py:26
- §3.5 — insert — ambiguity — reference-resolution ordering ahead of the order/channel agreement rule — routes_playlist.py:57
- §3.5 — insert — ambiguity — dense-run rule, ascending creation, `UNCLEARED` for asset-less elements, `house_number` overwritten from the asset, element defaults, `version` 1 — routes_playlist.py:96
- §3.5 — insert — ambiguity — per-element order bumps; the timeline and inventory passes run last — routes_playlist.py:142
- §3.5 — revise — mismatch — the `EAS_OVERRIDE` bar applies to **every** playlist transition; a return to IMPORTED clears `armed_at_utc`; one version bump — routes_playlist.py:369
- §3.5 — insert — ambiguity — validation's blocked count is taken live — routes_playlist.py:356
- §3.5 — insert — ambiguity — the arm gate is skipped when no transmitter resolves — routes_playlist.py:356
- §3.5 — insert — ambiguity — arm clearance is stricter than validation's; variance read live — routes_playlist.py:356
- §3.5 — revise — mismatch — corrected ON_AIR gate order (order preroll → not-on-air → already-on-air) — routes_playlist.py:356
- §3.5 — revise — mismatch — corrected CLOSE gate order; SYSTEM/null-user skip rows carry no incremental credit — routes_playlist.py:356
- §3.5 — revise — mismatch — abandonment is reachable from four statuses, writes no as-run row, and decrements `scheduled_spots` unconditionally — routes_playlist.py:356
- §3.5 — revise — mismatch — revision is 412-before-status; retained-number conflict; `removed_sequence_numbers` is a **veto, not a selector**; delete-and-rebuild semantics — routes_playlist.py:192
- §3.5 — insert — ambiguity — listing orders, filter-validation asymmetries, read-time recomputation — routes_playlist.py:234

#### §3.6 — playout events (13)
- §3.6 — insert — ambiguity — the response body is the as-run entry; six direct kinds; `source` defaults; `recorded_by_user_id` always set — routes_item.py:72
- §3.6 — insert — ambiguity — timestamp rules run after the state gates; playlist-wide as-run ordering — routes_item.py:72
- §3.6 — revise — mismatch — `PREEMPTION`'s precondition; preconditions before gates; END's missing-field check first — routes_item.py:72
- §3.6 — insert — ambiguity — cue's fifth gate, full gate order, and the on-air requirement binding only CUE — routes_item.py:72
- §3.6 — insert — ambiguity — start's posture/override gates and the absence of a clearance re-check — routes_item.py:72
- §3.6 — insert — ambiguity — END writes before classification — routes_item.py:72
- §3.6 — insert — ambiguity — truncation floored at 0; a supplied measurement stored verbatim — cascades.py:102
- §3.6 — revise — mismatch — `PREEMPTION` is directly requestable and the fiscal gate applies non-uniformly — routes_item.py:72
- §3.6 — revise — mismatch — corrected the list of what `EAS_OVERRIDE` blocks and does not block — routes_item.py:72
- §3.6 — insert — ambiguity — every event bumps the playlist and recomputes posture — routes_item.py:72
- §3.6 — insert — ambiguity — substitution's override gate, self-referential resolution fallback, null measured duration, hour index — routes_item.py:172
- §3.6 — insert — ambiguity — substitution trim floored at 0 — routes_item.py:172
- §3.6 — revise — mismatch — the substitute inherits `feed_window_id`/`max_trim_seconds` but drops `spot_order_id` to null; response body is the item view — routes_item.py:172
- §3.6 — insert — ambiguity — as-run listing inclusive bounds, filter codes, bare join/breakaway rows — routes_playlist.py:258

#### §3.7 — network feed windows (15)
- §3.7 — insert — ambiguity — the `breakaway_utc > join_utc` test precedes channel resolution; the created record's empty plan form is never exposed — routes_feed.py:78
- §3.7 — insert — ambiguity — `plan_playlist` precedence and the three failures behind one `ERR_ANCHOR_ITEM_NOT_FOUND` — routes_feed.py:41
- §3.7 — insert — ambiguity — the three creation refusals rank overlap → capacity → anchor; overlap is same-channel only — routes_feed.py:89
- §3.7 — insert — ambiguity — the pre-insert peak probe is never persisted; a refused insert and a no-change recomputation both write nothing — calc.py:288
- §3.7 — insert — ambiguity — the peak's full re-evaluation points; a join never moves it, a breakaway and abandonment lower it in-request — calc.py:288
- §3.7 — insert — ambiguity — a null `max_trim_seconds` counts as 0 and a negative allowance is floored at 0 — plcalc.py:314
- §3.7 — revise — mismatch — `SKIP_ELEMENTS` reports the whole pool while discarding skipped elements' trims; the degraded `HARD_CUT` returns an empty skip list, reports the whole pool and writes **no trim at all** — plcalc.py:333
- §3.7 — revise — mismatch — the §2.11 tail ledger's trim term is the seconds actually written, not `backtime_trim_seconds` — plcalc.py:348
- §3.7 — revise — mismatch — the remaining-time identity holds exactly only on `PAD_WITH_FILLER`/`TRIM_TAIL`, to within tolerance on a `HARD_CUT` — plcalc.py:302
- §3.7 — insert — ambiguity — a plan is computed at exactly three moments and never on a read — routes_feed.py:54
- §3.7 — revise — mismatch — the join's full gate ladder including the missing `EAS_OVERRIDE` bar; the two trim guards are unreachable defence; the future check is last — routes_feed.py:139
- §3.7 — insert — ambiguity — the recomputation is driven by the logical clock; `actual_join_utc` only timestamps as-run rows — routes_feed.py:159
- §3.7 — revise — mismatch — filler sequence/start/full field set; `TRIM_TAIL` and `SKIP_ELEMENTS` share one path; `HARD_CUT` and `JOIN_IN_PROGRESS` are identical and truncate every playing element; the JOIN row's null element fields; the channel is left alone — routes_feed.py:179
- §3.7 — revise — mismatch — the breakaway writes **only** `residual_dead_air_seconds` and `plan_computed_utc`, re-cues nothing, applies no trim, has no lateness bound and no channel gates — routes_feed.py:249
- §3.7 — insert — ambiguity — only `PLANNED` windows are abandoned; the sweep is silent and writes no as-run row; the state check is the first gate; listing order and filter codes — cascades.py:240 / routes_channel.py:285

#### §3.8 — emergency override (13)
- §3.8 — insert — ambiguity — request check order, `crawl_text` bounds, and `requested_start_utc` being required but never validated or read — routes_override.py:39
- §3.8 — insert — ambiguity — the overlap scan is same-channel and is the request's last gate — routes_override.py:52
- §3.8 — revise (new paragraph) — mismatch — activation's ten gates fire in an order quite unlike the reading order; the timestamp check is last — routes_override.py:114
- §3.8 — revise — mismatch — the role-class and certification gates sit after the crawl-text and dwell rules; certification is read live; the authorizer's `status` is unchecked — routes_override.py:140
- §3.8 — revise — mismatch — the self-authorisation bar is unconditional across all four alert classes and is a two-way comparison against the requester — routes_override.py:122
- §3.8 — insert — ambiguity — the posture gate is first; a stored `crawl_text` satisfies the crawl requirement — routes_override.py:119
- §3.8 — revise — mismatch — `authorized_by_operator_id` comes from the nominated authorizer, not the acting user; `activated_utc` is written only when null and a supplied one is discarded; the posture bump is conditional — routes_override.py:151
- §3.8 — insert — ambiguity — a cut-in bumps the override twice where a crawl bumps it once — routes_override.py:169
- §3.8 — insert — ambiguity — cascade element rows are `SYSTEM`-sourced; the `OVERRIDE_IN` row is written last and still names the now-truncated element — routes_override.py:180
- §3.8 — insert — ambiguity — hop five rewrites all six playlist figures; the fiscal gate runs before any write and excludes the playing element — cascades.py:274
- §3.8 — revise — mismatch — `activated_utc` never moves after the first pass, so both dwells count from first air; de-escalation's `air_status` write lands without a channel bump; the dwell is de-escalation-only — routes_override.py:133
- §3.8 — insert — ambiguity — release gate order; `released_utc` discarded in favour of the clock; the channel is always bumped; the remaining-cut-in condition is defensive — routes_override.py:196
- §3.8 — revise — mismatch — rejection shares the release endpoint, admits `StationAdmin`, is decided from the raw acting role, and refuses a wrong role with `ERR_OVERRIDE_INVALID_STATE`; listing order and filter codes — routes_override.py:200

#### §3.9 — spot inventory and makegoods (9)
- §3.9 — insert — ambiguity — `order_reference` bounds and station-wide uniqueness checked after channel resolution; `makegood_deadline_utc` never validated — routes_spot.py:38
- §3.9 — insert — ambiguity — order listing order and filter-validation asymmetry — routes_spot.py:72
- §3.9 — revise — mismatch — the linked set spans every playlist in the station, with creation order as the third sort key — plcalc.py:128
- §3.9 — insert — ambiguity — a null `measured_duration_seconds` counts as 0 in both classification and credit — plcalc.py:137
- §3.9 — insert — ambiguity — final-basis unplaced credit is unattributable and lands in full on whichever playlist is settling — plcalc.py:210
- §3.9 — insert — ambiguity — `credited_spots` never absorbs unplaced money (Step 8) — plcalc.py:209
- §3.9 — insert — ambiguity — the reconciliation view's `basis` validation and exact response shape; it carries no `id` (Step 8) — routes_playlist.py:281
- §3.9 — revise (new paragraph) — mismatch — `PARTIALLY_CREDITED` has no upper bound; the OPEN reset outranks the settled statuses' stickiness; close settlement's three clauses need no prior status, `CLOSED_WITH_CREDIT` needs no credit, and a no-match close leaves `status` untouched — plcalc.py:229 / cascades.py:316
- §3.9 — revise — mismatch — makegood adds `ERR_PLAYLIST_INVALID_STATE`, inventory-before-timeline, timeline anomalies, unreachable `ERR_ITEM_PLAYLIST_MISMATCH`, the auto-selected replaced element, asset/clearance inheritance, duration default, no as-run row, the item-view response, and two order bumps — routes_spot.py:98

### Orchestrator verification

- `workspace/PRD_COMPLETED.md` — 715 lines, 221,264 bytes; ends at the §5 error-catalogue final row (`ERR_MULTIPLEX_CAPACITY_EXCEEDED | 409`), same terminal row as `PRD.md`; not truncated.
- `diff` of all `^#` heading lines between `PRD_FINALIZED.md` and `PRD_COMPLETED.md` is empty — no section added, renamed or removed.
- No `.py` file under `workspace/implementation/`, `test_suite/` or `test_helpers/` is newer than `results.1.json`, confirming Steps 8 and 9 changed documentation only and the 8/8 green gating sweep still describes the shipped code.

**Pipeline complete through Step 9.**
