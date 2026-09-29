# Worklog — task_2160_injection_molding_job_shop

## Step 1: Create task directory — 2026-08-27T00:00:00.000Z

Created `tasks/task_2160_injection_molding_job_shop/` and `tasks/task_2160_injection_molding_job_shop/workspace/`.

## Step 3: Copy shared files — 2026-08-27T00:00:00.000Z

Copied `INSTRUCTION.md` to `tasks/task_2160_injection_molding_job_shop/workspace/INSTRUCTION.md`.

## Step 2: Generate scaffold — 2026-08-27T05:35:00.000Z

All three scaffold artifacts are generated and `scaffold_lint.py` passes clean on the first run.

## Files written
- `/home/ubuntu/github/CodingPRD/tasks/task_2160_injection_molding_job_shop/SCAFFOLD.yaml` (§1.0–§1.7, 2313 lines)
- `/home/ubuntu/github/CodingPRD/tasks/task_2160_injection_molding_job_shop/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8 only, 942 lines)
- `/home/ubuntu/github/CodingPRD/tasks/task_2160_injection_molding_job_shop/SCAFFOLD_CORNER_DESIGN.yaml` (§1.9 only, 1649 lines)

The pre-existing `worklog.md` and `workspace/` were left untouched. No sibling task directory was read — only the skill's own `SKILL.md`, `references/claim-extraction-guide.md`, `scaffold_lint.py`, and `examples/seed-tables-template.yaml`.

## Design summary (Expert-plus, per the "harder than expert" instruction)
- **Profile**: `workflow_orchestration` × `temporal_windowing`; layers = OCC, cascading side effects, dual-variant calculation, selector policy. Topology **flat** (all top-level collections, `api_prefix: ""`), shape **cyclic**, role model **segregation_of_duties**, self-referential FK (`PPAPSubmission.supersedes_submission_id`).
- **Surface**: 12 entities, 11 state machines (ProductionJob and Mold each carry two independent axes), 7 OCC concurrency rules, 14 calculations, 24 ordered validations, 60 endpoints, 57 errors, 6 roles.
- **Two parallel-dimension entities**: `ProductionJob` (`run_status` × `material_status`, with a SCHEDULED→BLOCKED→SCHEDULED loop) and `Mold` (`status` × `service_state`, with SERVICEABLE→PM_DUE→IN_MAINTENANCE→SERVICEABLE).
- **Signature trap**: the press uses **half-open windows + a 45-minute changeover buffer**, the mold uses **closed windows with zero buffer** — so a 1-minute gap is fatal on a press but sufficient on a tool, and a touching endpoint is fatal on a tool but irrelevant geometry on a press.
- **Two selectors on the same press pool** with deliberately different eligibility: quoting ignores qualification, job routing requires it — which is how the empty-candidate-set boundary is reached without making the setup unreachable.

## Verification performed
- `scaffold_lint.py <task-dir>` → `VERDICT: clean lint` (1185 calls scanned across §1.8+§1.9; 60 endpoints, 12 entities, 18 difficulty instances, 57 active corner instances).
- Custom checks I ran on top of the lint: **all 82 instance names unique**, **0 unresolved `grounds:` references** (resolver written against §1.1–§1.7), **every one of the 57 error codes appears in a design file** (I deleted `ERR_INTERIM_PPAP_EXPIRED` after finding it unreachable — the interim-ceiling breach auto-quarantines the mold, so `ERR_MOLD_QUARANTINED` always wins), and **zero forbidden concurrency vocabulary**.
- Every formula-derived assert literal was computed in Python first (quote 95¢ vs as-run 98¢, customer-owned 34¢, price floor 12¢, per-line rounding 2332 vs sum-then-round 2331, overhead 816, STRICT 72000 vs GOODWILL 32400 shortfall, 8000 utilization_bp / 14400¢ partial settlement, regrind 2000 bp pass / 2002 bp fail, day capacity 1224).
- `scenario:` round-trips **verbatim** (verified by string equality after YAML load — I switched it to folded `>-` for exactly this reason).

## Coverage counts
- §1.8: 9 rule_ids × 2 = **18 instances**, each with a full structured `setup_api_calls` chain from empty DB.
- §1.9: 9 sections, **64 instances** (57 executable + 7 `excluded_because` stubs pointing at named §1.8 instances).

## Step 4: Generate PRD — 2026-08-27T05:46:00.000Z

PRD generated at `workspace/PRD.md` — **468 lines, 86,855 bytes**.

**Withhold constraint honored:** neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced. Only `SCAFFOLD.yaml`, the skill spec, and `section-2.2-response-structure.md` were read.

**Structure**: §1 three-paragraph intro; §2 with ten subsections (RBAC, verbatim response structure, pagination + reverse-navigation filters, identity/logical clock, stale-view rejection, integer arithmetic & rounding, the 24-step screening ladder, parallel state axes & cascade chains, press/tool occupancy semantics, shop-floor reversibility); §3 with nine lifecycle-ordered subsections; §4 4-column endpoint table; §5 2-column error table. Written incrementally across seven append calls — no oversized Write.

**Hard Contract Reports**

Field coverage check:
- entities[].fields: 103 required, 103 present, 0 missing
- endpoints[].request_body: 65 required, 65 present, 0 missing
- endpoints[].query_params/path_params: 19 required, 19 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 24 checked, 24 expressed in prose (§2.7 ordered ladder), 0 missing
- concurrency_rules[] OCC rejections: 7 checked, 7 expressed (write_endpoint + expected_<parent>_version + error_id + 412 all named in §2.5), 0 missing
- state_machines[].transitions: 11 machines / 62 transitions checked, 62 fully expressed, 0 missing
- calculations[]: 14 checked, 14 fully expressed (incl. both quote_piece_price variants and both capacity_commit_settlement variants), 0 missing
- validations[] conditions: 24 checked, 24 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 60 endpoints checked, all side effects and all applies_to scopes expressed, 0 missing
- entities[].fields[] structured content: 103 checked, 103 reconstructible from prose, 0 missing
- sibling-branch symmetry: 6 groups checked, 6 with equal prose density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 771; tokens starting with `/`: 0; bare HTTP-method tokens: 0; method+path combined tokens: 0
Status: PASS

Additional verification: §2.2 matches the canonical file byte-for-byte; all 57 error IDs appear in §2/§3 narrative (not just the §5 table); no pseudocode operators survive anywhere in §1–§3; no fuzzy/approximating words; §4 has exactly 60 rows / 4 columns and §5 exactly 57 rows / 2 columns; the file ends at §5 with no audit footer.

Two scaffold ambiguities were resolved toward the literal reading and stated unambiguously in prose: (1) accepting a quote increments `Mold.version` by 1 even when the tool is already `SAMPLING` (status change is a no-op, version bump is not); (2) closing a maintenance order with `reset_shot_counter` false is declared only when `shots_since_pm` is at or above `pm_interval_shots`, and is otherwise rejected with `ERR_INVALID_STATE`.

Orchestrator verification: all five sections (§1–§5) present, file ends at the error catalogue — no doc-generator truncation.

## Step 6 (attempt 1, DISCARDED — design-index contamination) — 2026-08-27T06:10:00.000Z

The first implementation-generator subagent produced a complete 9-module Flask implementation and reported self-verifying it against "all 9 difficulty-design instances (18 scenarios) and ~25 corner-design instances".

Orchestrator transcript audit (tool_use input fields only, extracted via python/json — transcript body never loaded into orchestrator context): **11 of 71 tool calls referenced the withheld design indices**, including a full `Read` of `SCAFFOLD_DIFFICULTY_DESIGN.yaml` plus two offset re-reads, and five separate grep/awk/sed/python extractions of `SCAFFOLD_CORNER_DESIGN.yaml` assert blocks.

Verdict: the implementation was written with sight of the test answer key. A green first sweep would have measured nothing. **Discarded in full** — moved to scratchpad as `implementation_CONTAMINATED_step6_v1`, not reused, not consulted.

Root cause: the entrance skill's Step 6 prompt template carries no withhold constraint (unlike Step 4's, which does). The impl-generator agent found the files by listing the task directory and treated them as available context.

## Step 6 (attempt 2) — relaunched 2026-08-27T06:12:00.000Z

Relaunched with an explicit non-negotiable withhold block naming both design-index paths, forbidding all read vectors (read/grep/awk/sed/wc/head/tail/python-parse), forbidding `test_suite/`, `test_helpers/`, `worklog.md`, sibling tasks, and any recursive/glob shell command that could sweep them in; self-verification restricted to scenarios derived from PRD.md prose by hand.

## Step 5: Generate unit tests — 2026-08-27T06:15:00.000Z

Test infrastructure and suite are complete for `task_2160_injection_molding_job_shop`.

## What was generated

**`test_helpers/`** (9 files, ~62 KB)
- `types.py` — 12 entity TypedDicts + 15 status enums (both parallel axes for `Mold` and `ProductionJob`). All entities carry `common_fields: true`, so all TypedDicts include `updated_at`/`version`.
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (65 endpoints incl. `/_clock/set_current_utc`).
- `api_errors.py` — all 57 error ids + HTTP map, registered via `set_error_http_status_map`.
- `assertions.py` — per-entity assertions plus domain invariants (`parts_molded_total == good + scrap`, `job_total == direct + overhead`, lot-mass conservation, `first_pass_yield_bp == 10000` when nothing molded).
- `factories.py`, `constants.py`, `test_users.py` (`make_customer_rep_headers` for the one `entity_backed:Customer` role; `qe-alice`/`qe-bob` split for segregation of duties), `fixtures.py` (~470 lines, tiers 1–5: `setup_qualified_shop` → `setup_sampling_tool` → `setup_ppap_under_review` → `setup_approved_tool` → `setup_scheduled_job` → `setup_staged_job` → `setup_running_job`, plus `add_job` for sibling/collision scenarios).

**`test_suite/`** — `conftest.py` + 12 domain-named files, **93 tests**, all collecting cleanly.

## Coverage against the design-index-only contract

| Queue | Instances | Result |
|---|---|---|
| Difficulty (§1.8) | 18 | **18/18 with >=2 tests** (37 tests total) |
| Corner (§1.9), executable | 57 | **56/57 with >=1 test** |
| Corner `excluded_because:` stubs | 7 | not translated; all 7 `difficulty_instance` cross-references verified to resolve |

Every test carries exactly one `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` line as the final docstring line, copied verbatim from the source yaml. A verification script confirmed: 1 tag per test, tag is last line, every tag resolves to a real non-stub instance, and **every quoted PRD sentence survives a whitespace-normalised literal match against `workspace/PRD.md`**. No `skip`/`skipif`/`xfail` anywhere; no "scaffold"/table references leaked into comments.

## The one deliberate skip

`Corner/entities/customer_create_with_client_supplied_id_returns_invalid_request` — asserts that `POST /customers` carrying an extra `id` key returns 400. **PRD gap**: §2.7 step 4 enumerates the request-shape checks as "*every required body field is present, every type is correct, every enum member is recognized, every integer sits inside its declared range, and pagination parameters are in range*" — it never says unknown body keys are rejected, and §2.4 only says `id` is server-minted. Two PRD-only implementers would split on strict-schema vs. ignore-unknown-keys, so the instance fails unique derivability. Gap left as a gap, no placeholder emitted.

## Notable verification done during translation

All literal expected values in the indices were re-derived against the PRD formulas before being copied, including the quote chain (`94828`/`95`, `33828`/`34`, `2669`/`12` floor), the as-run divergence (`42` s cycle, `9500` bp yield, `98`, variance `3`), the round-per-line cost roll (`1166` + `1166` = `2332`, *not* `2331`; overhead `816`; total `3148`), regrind boundaries (`2000` bp exact vs `2002` bp), and both settlement variants (`72000` strict vs `32400` goodwill; partial `480`/`8000`/`120`/`14400`). Window geometry was cross-checked so each interval test isolates its intended gate — e.g. the daily-capacity corner test uses an exactly-45-minute press gap and non-touching mold windows so only the day cap can fire.

**Note for Step 7:** this test suite is UNCONTAMINATED with respect to the Step 6 attempt-1 leak — it was generated concurrently from the design indices (its legitimate source) and never saw `implementation/`. The implementation it will be run against is the attempt-2 (clean) build.

## Step 6 (attempt 2, ACCEPTED): Generate implementation — 2026-08-27T06:40:00.000Z

## Withhold constraint

**I did not read `SCAFFOLD_DIFFICULTY_DESIGN.yaml` or `SCAFFOLD_CORNER_DESIGN.yaml`** — not by any tool, command, glob, or recursion. I also did not read anything under `test_suite/`, `test_helpers/`, `worklog.md`, or any sibling `task_*/` directory. Every path I opened was addressed by its exact full name.

**Complete list of files read:**
1. `skills/prd-bench-implementation-generator/SKILL.md`
2. `tasks/task_2160_injection_molding_job_shop/workspace/INSTRUCTION.md`
3. `tasks/task_2160_injection_molding_job_shop/SCAFFOLD.yaml`
4. `tasks/task_2160_injection_molding_job_shop/workspace/PRD.md`

## What was built

`workspace/implementation/` — Python + Flask, ~2,200 lines across 8 modules plus `start.sh` and `requirements.txt`:

- `common.py` — logical clock (starts at `2026-08-01T00:00:00Z`, never falls back to wall time), 57-entry error->HTTP catalogue, `meta`/`response_type`/`data` envelope, `X-User-ID`/`X-User-Role` auth, in-memory `Store` (12 dicts, empty at boot, no seeding anywhere), pagination and filter screening
- `validation.py` — ladder step 4 (shape) and step 5 (whole-minute UTC window) screening
- `calcs.py` — all 14 calculations' constants and pure integer arithmetic (`round_half_up` as `(2a+b)//(2b)`, ceil, floor); no floats anywhere
- `services.py` — gates, both press selectors, half-open press windows with the 45-minute changeover vs. closed zero-buffer mold windows, press minute ledger, the three cascade chains, and the recomputation engine
- `routes_master.py` / `routes_commercial.py` / `routes_production.py` — all 60 endpoints
- `app.py`, `start.sh` (guarded pip install, `exec python3 app.py`, `0.0.0.0:$PORT`, boots in ~0.6 s from any cwd)

## Verification

Drove the running server over HTTP with 8 hand-written scenario scripts — **~910 assertions, all passing** — with every expected number derived by hand from PRD formulas, not from any answer key. Coverage included: the eleven pricing steps (lot 56845 c / piece 57 c, and the 12 c floor), per-line-then-sum cost rolling with a half-cent overhead (4092, not 4091), the 9000 bp run-at-rate boundary, the 45-minute changeover boundary (10:44 collides, 10:45 accepted), touching closed mold windows, the exact 1224-minute daily ceiling, the 850-of-1000-minute availability formula, strict vs. goodwill shortfall fees, the PM and interim-expiry threshold cascades, reversal restoring every ledger with zero drift, the three-link transfer cascade, and a real two-thread OCC race (one 200, one 412, ledger consistent).

**Two self-flagged judgment calls where the PRD was ambiguous**, both resolved toward §2.7's normative ladder over prose order:
1. capacity availability (step 22) is screened **before** credit hold (step 24)
2. mold-window overlap (step 17) **before** `ERR_MAINTENANCE_ALREADY_OPEN` (step 23)

Caller-supplied datetime strings are echoed back verbatim; `created_at`/`updated_at` use the mandated three-fractional-digit form.

**Orchestrator transcript audit (tool_use input fields only):** 36 tool calls scanned, **0 calls touching `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `test_suite/`, `test_helpers/`, or `worklog.md`.** Withhold claim verified — this implementation is uncontaminated and is the one Step 7 runs against.

## Step 7: Run tests and iterate — 2026-08-27T06:50:00.000Z

All 8 parallel rounds passed on the first sweep. Exiting per the protocol.

**Iterations run:** 1 (a single 8-round parallel stability sweep; no fixes were needed).

**Sweep result:** all 8 concurrent rounds returned `passed == total == 93`, `failed == 0`, `errors == 0`, `skipped == 0`.

- `results.1.json` … `results.8.json` — each `93/93`.
- Union of failing tests across all 8 rounds: **empty**. No flakiness surfaced — the 8 rounds advanced in lockstep through all 12 files with identical pass sets, so the timing-sensitive areas (the OCC race tests, the changeover-boundary window tests, the daily-capacity boundary) held on every attempt, and the runner's file-locked port registry kept the 8 rounds off each other's ports.

**Tests deleted:** none. STEP 0 produced an empty failure set, so STEP 1's coverage / unique-derivability adjudication never had a candidate to run against.
**Fixes applied to `test_helpers/`:** none.
**Fixes applied to `test_suite/`:** none.
**Fixes applied to `implementation/`:** none.

### On the two self-flagged PRD ambiguities

Both judgment calls the implementation generator flagged were resolved by it toward §2.7's normative ladder, and both survived the sweep untouched:

1. **Capacity availability (step 22) before credit hold (step 24)** — PRD §2.7 numbers these explicitly and prefaces the list with "the **first** check that fails determines the response. This ordering is normative". The test suite agrees with that reading; no test asserted the opposite precedence.
2. **Mold-window overlap (step 17) before `ERR_MAINTENANCE_ALREADY_OPEN` (step 23)** — same normative ladder; §3.8 states the touching-window case raises `ERR_MOLD_WINDOW_CONFLICT` without claiming uniqueness pre-empts it. Again no test contradicted the ladder order.

The concern that failures would cluster there did not materialize: the ladder-order reading the implementation chose is the one the tests encode, and **the independence of the two generators (verified by transcript audit) means that agreement is genuine signal rather than an artifact**.

**Note on repo state:** no edits to any file under the task directory. The only new files are the eight `results.N.json` artifacts.

### Orchestrator independent verification

- All 8 `results.N.json` re-read directly: `93/93/0/0/0` confirmed in every round.
- Seeding/persistence grep over `implementation/*.py` (`seed|preload|sqlite|open(...'w'|json.dump|pickle`): **0 hits** — storage is in-memory only, no boot-time data.
- `skip`/`xfail` grep over `test_suite/`: **0 hits**. Test count 93 — unchanged from generation, confirming zero deletions.

## Step 8: Finalize PRD — SKIPPED — 2026-08-27T06:52:00.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. `<step_7_diff>` is empty, so Step 8 has no scope.

**Why the usual inference behind this skip is NOT being relied on here.** "Clean first sweep ⇒ PRD already pinned every behavior" is unsound: a green suite proves impl and tests *agree*, not that PRD *determines*. The suite only asserts what the design indices chose to probe; every PRD silence on an unprobed path stays invisible to it. Step 9 is therefore treated as load-bearing rather than a formality, and is given the impl-generator's two self-flagged judgment calls plus a directive to demand a verbatim PRD sentence for every impl behavior — with particular attention to cascade paths the suite exercised only from the happy side.

## Step 9: Complete PRD — 2026-08-27T07:05:00.000Z

45 paragraphs revised, all in place, structure intact.

**Files:** `PRD.md` 468 lines / 86,855 chars -> `PRD_COMPLETED.md` 468 lines / 101,272 chars (**+14,417 chars**, 45 paragraphs revised, 0 lines added/removed). Structure verified identical: §1–§5 present, 19 subsections, 60 endpoint rows, 57 error rows.

**Counts:** 47 edits total — **42 ambiguity-pins**, **5 mismatch-revisions**.

### Changes

**§2 — global**
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` -> `ERR_INVALID_REQUEST`; undeclared query params ignored — `common.py:283-301`
- §2.3 — insert — ambiguity — enum filters reject unknown values (400); FK filters never 404, just return an empty page; filters applied after ordering, before pagination — `common.py:304-333`, `routes_master.py:77-83`
- §2.4 — insert — ambiguity — clock echoes `to_iso8601` verbatim; non-UTC-offset/unparseable -> 400; no whole-minute rule on the clock — `routes_master.py:317-326`
- §2.4 — insert — ambiguity — zone-less window endpoint read as UTC, non-zero offset -> `ERR_INVALID_WINDOW`; missing/non-string endpoint -> `ERR_INVALID_REQUEST` at step 4 — `common.py:127-144`, `validation.py:411-430`
- §2.6 — insert — ambiguity — equal `created_at` (frozen logical clock) tie-broken by creation sequence — `common.py:183-186`
- §2.7 step 4 — insert — ambiguity — **unknown body keys ignored**; explicit `null` == absent; unparseable/non-object body handling; only transfer `decision_reason` and report `reversal_reason` persist, all other `reason`/`note` discarded — `validation.py:348-362`
- §2.7 step 11 — insert — ambiguity — specific mold errors outrank generic; every other disallowed status -> `ERR_MOLD_NOT_PPAP_APPROVED` — `services.py:41-53`
- §2.7 — insert — ambiguity — three added precedence consequences (**capacity availability before credit hold**; **mold-window before `ERR_MAINTENANCE_ALREADY_OPEN`**; lifecycle before credit hold), plus "ladder governs over §3 narration order" — `routes_commercial.py:446-450`, `routes_production.py:429-433`

**§3.1–3.3 — masters, qualification, quoting**
- §3.1 — insert — ambiguity — `credit_hold` default also applies to explicit `null`; `name` unconstrained — `routes_master.py:26-33`
- §3.1 — insert — ambiguity — press `note` not persisted; no state precondition; same-status set still bumps `version` — `routes_master.py:86-95`
- §3.1 — revise — ambiguity — retire error mapping (`SAMPLING`/`INTERIM_APPROVED` -> `ERR_INVALID_STATE`), lifecycle checked before unfinished-jobs; service_state/transfer do not block — `routes_master.py:206-217`
- §3.1 — insert — ambiguity — tonnage-band inversion -> `ERR_INVALID_REQUEST`, before the `customer_id` FK resolves — `routes_master.py:111-114`
- §3.2 — insert — ambiguity — qualification creation ungated on tool lifecycle/service and press status — `routes_master.py:226-234`
- §3.2 — revise — mismatch — **every** booking clears `actual_parts_per_hour` (not only after a failure); booking from `RUN_AT_RATE_SCHEDULED`/`QUALIFIED` -> `ERR_INVALID_STATE` checked first; trial window never collision-screened and reserves no minutes — `routes_master.py:278-297`
- §3.2 — insert — ambiguity — recording the verdict consults neither tool lifecycle nor press status — `routes_master.py:300-314`
- §3.3 — insert — ambiguity — quote drafting ungated on tool lifecycle; initial null price/decision fields — `routes_commercial.py:36-51`
- §3.3 — revise — ambiguity — pricing order: `DRAFT` state -> press FK -> lifecycle -> cavitation (`ERR_INVALID_REQUEST`) — `routes_commercial.py:84-94`
- §3.3 — revise — ambiguity — `ACCEPT`: lifecycle gate precedes credit hold (narrative was inverted) — `routes_commercial.py:144-147`

**§3.4–3.5 — PPAP, resin**
- §3.4 — insert — ambiguity — PPAP birth fields; `supersedes_submission_id` must resolve but need not be `REJECTED`/same-mold; `quote_id` status unconstrained — `routes_commercial.py:176-194`
- §3.4 — insert — ambiguity — `interim_expiry_shots` optional on `APPROVE`/`REJECT`, range-checked then ignored — `routes_commercial.py:266-267`
- §3.4 — insert — ambiguity — quarantine error mapping incl. `NEW` -> `ERR_INVALID_STATE` — `routes_master.py:173-181`
- §3.4 — insert — ambiguity — release error mapping for non-`QUARANTINED` statuses — `routes_master.py:186-191`
- §3.5 — revise — ambiguity — staging adds the `material_status != UNSTAGED` -> `ERR_INVALID_STATE` gate, names `ERR_RESIN_LOT_INSUFFICIENT`, fixes gate order, notes tool is not consulted — `routes_production.py:207-217`
- §3.5 — insert — mismatch — `DEPLETED` is one-way: a reversal restores grams but not the status; lot recompute writes (and bumps `version`) only on real change — `services.py:265-274`

**§3.6 — production job**
- §3.6 — insert — ambiguity — job opening screens no press window, mold window or daily capacity — `routes_production.py:106-113`
- §3.6 — revise — ambiguity — scheduling gate order is tool-then-machine (ladder), not press-first — `routes_production.py:186-194`
- §3.6 — revise — ambiguity — start gate order material -> lifecycle -> lot -> service; press status and transfer not consulted — `routes_production.py:227-236`
- §3.6 — insert — ambiguity — unblock re-checks neither press `status` nor `active_transfer_id` — `routes_production.py:278-285`
- §3.6 — revise — ambiguity — complete: `ERR_INVALID_STATE` for zero shots; `STAGED -> CONSUMED` **conditional** on the axis actually being `STAGED`; all rollups rebuilt — `routes_production.py:246-252`
- §3.6 — revise — ambiguity — manual cancel **clears** an existing `block_reason`; `reason` not persisted — `services.py:200-207`, `routes_production.py:266`
- §3.6 — insert — ambiguity — job may only be opened against `ACCEPTED`; other statuses -> `ERR_INVALID_STATE`, tested before all gates — `routes_production.py:100-101`

**§3.7–3.8 — reporting, toolroom**
- §3.7 — insert — ambiguity — report birth fields; posting does **not** re-check lot release (a `HOLD`/`REJECTED`/`DEPLETED` lot still accepts reports) — `routes_production.py:342-362`
- §3.7 — insert — ambiguity — job always written on posting/reversal; lot and mold written only on actual field change — `services.py:265-274`, `services.py:285-324`
- §3.7 — insert — ambiguity — as-run degenerate inputs: yield 0 bp -> divisor 1, unset `actual_cycle_time_sec` -> 0 s — `calcs.py:503`, `services.py:336`
- §3.7 — revise — mismatch — reversal re-runs only the four standing recomputations; **as-run price and variance are frozen**, never revisited; reversal allowed on any `run_status` — `routes_production.py:393-416`
- §3.7 — insert — ambiguity — approved ceiling of exactly 0 bp is a real ceiling, not a fallback to 1,500 — `routes_production.py:325-327`
- §3.7 — insert — ambiguity — a job with no bound lot fails the sufficiency gate with `ERR_RESIN_LOT_INSUFFICIENT` — `routes_production.py:342-344`
- §3.8 — insert — ambiguity — PM reset-instant tie-break by creation order; inclusive report comparison uses the same tie-break — `services.py:277-299`
- §3.8 — insert — mismatch — interim gate is one-way (a reversal does not un-quarantine); when both gates fire, PM cascade wins and jobs carry `MOLD_PM_DUE`; no-op recompute does not bump `version` — `services.py:301-324`
- §3.8 — revise — ambiguity — maintenance order: window conflict checked **before** `ERR_MAINTENANCE_ALREADY_OPEN`; opening ungated on tool lifecycle; `kind` inert — `routes_production.py:428-433`

**§3.9, §4 — commercial, routing**
- §3.9 — insert — ambiguity — transfer request ungated on tool lifecycle; scope test placed after FKs and before uniqueness; `decision_reason` starts unset — `routes_commercial.py:330-350`
- §3.9 — revise — mismatch — completion drives the tool to `TRANSFERRED` **from any status**, not only `PPAP_APPROVED` — `routes_commercial.py:418`
- §3.9 — revise — ambiguity — capacity availability checked **before** credit hold (moved credit-hold sentence); press status and job occupancy not consulted — `routes_commercial.py:438-450`
- §3.9 — insert — ambiguity — settlement matches the tool's `customer_id` as it reads at settlement time — `routes_commercial.py:502`
- §3.9 — insert — ambiguity — `settlement_cents` is inert, never read by any calculation — `routes_commercial.py:329`
- §4 — insert — ambiguity — unknown path -> `ERR_INVALID_REQUEST`/404, bad method -> `ERR_INVALID_REQUEST`/405, trailing slash insignificant — `app.py:586, 597-601`

The two generator-flagged judgment calls and the test generator's skipped `POST /customers` unknown-body-key case are all now pinned (§2.7 consequences, §3.8, §3.9, and §2.7 step 4 respectively).

### Orchestrator verification of Step 9 output
- `PRD_COMPLETED.md`: 468 lines (identical to `PRD.md`), 101,272 chars (+14,417). All five sections `## 1`–`## 5` present at the same line offsets.
- §4 table rows: 62 in both files. §5 table rows: 59 in both files. No section lost, no row added or dropped — edits are strictly in-paragraph.

## Post-pipeline: green-sweep validation (orchestrator) — 2026-08-27T07:20:00.000Z

A green first sweep is not self-validating: a vacuous suite, a leak-tuned implementation, and a genuinely complete PRD all print the same `passed == total`. Two checks were run to discriminate.

**1. Staleness check — PASS.** Newest `implementation/` source mtime `06:23:22` (`start.sh`, `app.py`); oldest `results.N.json` mtime `06:39:11`. Results postdate every source, so the sweep ran against the current (attempt-2, uncontaminated) build — not a stale one left over from the discarded attempt-1 implementation.

**2. Mutation test — suite discriminates.** `implementation/` was copied to the scratchpad and two boundary constants in `calcs.py` were flipped, then the full 93-test suite was run against the mutant:

| Mutation | Result |
|---|---|
| `CHANGEOVER_BUFFER_MINUTES` 45 -> 44 | **KILLED** — `test_06::test_a_forty_four_minute_gap_still_collides_on_the_press` |
| `RUN_AT_RATE_MIN_BP` 9000 -> 8999 | **SURVIVED** |

Mutant total: 92 passed / 1 failed / 93. The killed mutation proves the instrument discriminates — the suite is not vacuous, and its press-window boundary assertions bind.

**The surviving mutation is a test-coverage gap, not a PRD gap.** Lowering the threshold to 8,999 changes behavior only for an achievement of exactly 8,999 bp, and no design instance generates that input — the indices probe the inclusive side (exactly 9,000 qualifies) and a far-below case, never the one-basis-point-under case. PRD_COMPLETED.md §3.2 line 203 already pins the rule unambiguously: *"If that achievement is at least 9,000 basis points — ninety percent of contract, with an exact ninety percent qualifying — the row moves `RUN_AT_RATE_SCHEDULED → QUALIFIED`; below it, the row moves `RUN_AT_RATE_SCHEDULED → FAILED`."* A PRD-only implementer derives 9,000 correctly, so no PRD edit is warranted.

No test was hand-written to close this gap — authoring a test against an implementation one can see would violate Step 5's design-index-only contract. Logged instead as **scaffold-generator feedback: `boundary_precision_check` instances should generate the just-below-threshold input alongside the at-threshold one.**
