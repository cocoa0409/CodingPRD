# Worklog — task_2537_bridge_inspection_load_rating_program

## Step 1: Create task directory — 2026-09-03T07:35:05.667Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2537_bridge_inspection_load_rating_program` and its `workspace/` subdirectory. Index 2537 was pre-assigned by the invoking pipeline; no scan of `./tasks/` was performed and no other task directory was created.

## Step 2: Generate scaffold — 2026-09-03T09:10:43.473Z

All three scaffold artifacts for task 2537 are complete and lint-clean.

## Output files (all under `/home/ubuntu/github/CodingPRD/tasks/task_2537_bridge_inspection_load_rating_program/`)

| File | Lines | Bytes |
|---|---|---|
| `SCAFFOLD.yaml` | 3714 | 178,741 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1616 | 117,361 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 3781 | 269,326 |

## Contents

- **`SCAFFOLD.yaml`** (§1.0–§1.7 only; no `scaffold_difficulty_design` / `scaffold_corner_design` keys): 14 entities, 10 state machines (cyclic; `CriticalFinding` carries three independent status dimensions), 2 OCC rules (`load-rating-create-stale-bridge` / `candidate-create-stale-cycle`), 20 calculations (two dual-variant: operating-vs-inventory load rating, CONDITION_BASED-vs-RISK_BASED priority score), a 35-rung ordered validation ladder, 69 endpoints (incl. two computed-read projections and the `POST /_clock/set_current_utc` logical clock with the mandatory `2026-08-01T00:00:00Z` startup default), 43 error codes, 7 roles under `role_model: segregation_of_duties`.
- **`SCAFFOLD_DIFFICULTY_DESIGN.yaml`**: single top-level key, 9 rules × 2 instances = 18.
- **`SCAFFOLD_CORNER_DESIGN.yaml`**: single top-level key, the guide's nine sections — entities 12, state_machines 13, calculations 11, validations 7, endpoints 6, errors 19, rbac 9, complexity_layers 7, consistency_model 1 (85 rows: 62 active instances + 23 `excluded_because` stubs, every stub citing a real §1.8 instance name; zero name collisions across the two design files). All claim types/sections come from `references/claim-extraction-guide.md` only; the entity-topology instance uses `claim_type: graph`; the "Bulk action" endpoint row is documented as inapplicable in a YAML comment because §1.5 declares no bulk write.

## Lint

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(Coverage: 69 endpoints, 14 entities, 18 §1.8 instances, 62 §1.9 instances, 827 calls scanned.)

## Notes / fixes made this session

- Two arithmetic errors caught by re-deriving numbers rather than trusting drafts: the redistributed-DECK BHI (weighted sum is 47.90/0.75 → **63.87**, not the drafted 47.10/62.80), and an earlier 3-element BHI (**67.85**) with group ratings 7/3/8.
- Removed the last two occurrences of forbidden concurrency vocabulary ("simultaneously") from both design files.
- One YAML parse break fixed: an unquoted `$.data[0].id` inside a flow mapping (replaced with a bridge read, since that list was empty in that recipe anyway).
- No sibling task directory was listed, globbed, grepped, or read at any point; everything derives from the scenario text, `SKILL.md`, the claim-extraction guide, and this task's own `SCAFFOLD.yaml`.

Orchestrator verification: all three files exist, are non-trivial, and parse as valid YAML with the expected top-level keys.

## Step 3: Copy shared files — 2026-09-03T09:10:58.206Z

Copied `./INSTRUCTION.md` to `tasks/task_2537_bridge_inspection_load_rating_program/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T09:28:41.427Z

PRD generation is complete and verified.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2537_bridge_inspection_load_rating_program/workspace/PRD.md` — **560 lines**, ends cleanly at the last row of the §5 error table (`ERR_BRIDGE_NOT_INSPECTED | 422`), no audit footer.

**Structure written:** §1 Introduction (3 paras) · §2 Global Specifications with 2.1 RBAC (all 7 roles), 2.2 verbatim response-structure block, 2.3 Pagination, 2.4 Logical Clock, 2.5 Common Resource Properties, 2.6 Pinned Rounding Order, 2.7 Cascade Discipline, 2.8 the full 33-rung validation precedence ladder, 2.9 both OCC rules, 2.10 Qualification & Segregation of Duties, 2.11 Service Posture & Inspection Frequency Policy · §3 Business Logic in 9 subsections (inventory/roster, inspection scheduling, QA + 5-hop acceptance cascade, load rating/sealing/posting, critical findings + 4-hop closure cascade, scour + plans of action, permits, capital programming waterfall, federal reporting) · §4 endpoint table (4 columns) · §5 error table (2 columns).

**Verification run:**
- `wc -l` → 560. `tail -40` → ends at a real table row.
- Endpoint rows: **69/69**. Error rows: **43/43**. Table shapes confirmed: §4 exactly 4 columns, §5 exactly 2 columns.
- **Contract 1 (field-name coverage): PASS** — programmatic diff of 202 required identifiers (all `entities[].fields[].name`, all endpoint `input`, and all computed-read output keys) against every backticked token in the PRD: **0 missing**. Two passes were needed; the first found `inspection_id` (ElementCondition) missing and it was added to §3.2.
- **Contract 2 (rule coverage): PASS** — all 33 validation rungs present in §2.8 with error IDs, HTTP statuses and `applies_to` scopes, in scaffold priority order (renumbered 1–33 with the scaffold's gaps at 4 and 32 closed, relative order preserved and re-verified against the scaffold list); both `concurrency_rules` fully named (endpoint + occ_field + error_id + 412); all 4 multi-hop cascades written hop-by-hop; all 23 calculations covered with worked examples; mechanical checks confirmed **every** state value from all 12 state-machine blocks and **every** entity enum value appears in backticks (0 missing), and every declared transition is described including the system-driven ones (rating supersede, candidate supersede, cycle lock/submit/close/return, permit revoke, and all 9 `service_posture` posture moves).
- **Contract 3 (§3 path purity): PASS** — extracted §3 (1001 backticked tokens) and scanned for tokens beginning with `/`, bare HTTP methods, and method+path combinations: **0 violations**; also 0 raw unbacktick'd paths or `METHOD /path` strings. Endpoints in §3 are referenced only by state-transition, role+action, or capability framing.
- No fuzzy quantifiers and no pseudocode operators (`==`, `>=`, `+=`, `min(`, `round_half_up(`, `IN {`, bare `AND`) survive anywhere in the document.

**Two scaffold-fidelity corrections made during verification** (both were wrong in my working notes and are now fixed): permit analysis is a **separate** `RECEIVED → ANALYZED` action, not part of application filing; and `RESTRICTED → POSTED` is not a declared posture transition, so the resolution fallbacks now list only `CLOSED → POSTED`, `CLOSED → OPEN` and `RESTRICTED → OPEN`.

**Inventory counts differ from the task prompt** — actual scaffold contents govern and all were covered: **23** calculations (not 20), **33** validation rungs (not 35; scaffold priorities run to 35 with gaps at 4 and 32), **12** state-machine blocks over 10 entities (not 10; `CriticalFinding` has 3 independent dimensions and `Bridge` has a `service_posture` dimension). Endpoints (69) and error codes (43) matched exactly.

The two withheld design files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced, and no sibling task directory was read.

**Orchestrator anti-truncation check:** independently ran `wc -l` (560), `tail -25` and a heading scan. The file ends at the final row of the §5 error table — a real section boundary, not mid-sentence — and all expected §1–§5 headings including §2.4 Logical Clock, §2.8 the validation ladder, §2.9 OCC, §3.1–§3.9, §4 and §5 are present. No regeneration needed.

## Step 6: Generate implementation — 2026-09-03T10:10:00.000Z

(Steps 5 and 6 were launched as concurrent background subagents. Orchestrator note: the two Agent calls went out in two consecutive assistant messages rather than one, so Step 6's impl generator could in principle have seen `test_suite/`. To preserve the benchmark's physical isolation, Step 6's prompt carried an ABSOLUTE HARD CONSTRAINT forbidding any read/list/glob/grep of `test_helpers/`, `test_suite/`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml`, restricting its inputs to INSTRUCTION.md + SCAFFOLD.yaml + PRD.md, and forbidding `ls` of the task root. Step 6 reported working only inside `workspace/implementation/`. Step 6 finished before Step 5.)

Implementation is complete, verified, and the test server has been shut down.

## Location
`/home/ubuntu/github/CodingPRD/tasks/task_2537_bridge_inspection_load_rating_program/workspace/implementation/`

## Files and line counts (4036 lines total)
| file | lines | role |
|---|---|---|
| `start.sh` (+x) | 8 | guarded `pip install` only if `import flask` fails, then `exec python3 app.py` |
| `requirements.txt` | 1 | `flask>=2.0` |
| `app.py` | 68 | `create_app()`, 6 blueprints, `strict_slashes=False`, ApiError/HTTPException/catch-all handlers |
| `errors.py` | 83 | all 42 catalog error ids -> HTTP status |
| `db.py` | 117 | in-memory `Store` (14 dicts), logical clock, id/version/timestamp helpers |
| `middleware.py` | 58 | header auth, 7 roles, entity-backed vs opaque |
| `response.py` | 78 | meta/response_type/data envelope, pagination, error envelope |
| `params.py` | 284 | body + query validation, `Decimal` parsing |
| `calc.py` | 503 | every derived quantity (RHU, indices, intervals, rating math, permit math, scoring, budget, compliance) |
| `serializers.py` | 359 | per-entity field projections |
| `services.py` | 506 | rollups, settle/idempotent recompute, multi-hop cascades |
| `routes_core.py` | 274 | clock, personnel, bridges, per-bridge compliance-summary |
| `routes_inspections.py` | 377 | inspections + element conditions |
| `routes_findings.py` | 261 | critical findings + notification logs |
| `routes_ratings.py` | 426 | load ratings, scour evaluations, plans of action |
| `routes_permits.py` | 235 | permit applications + per-bridge analyses |
| `routes_program.py` | 398 | program cycles, candidates, federal submissions |

## Verification evidence
- `python3 -m py_compile *.py` -> `PY_COMPILE_OK`; `__pycache__` removed afterwards.
- **Endpoint parity: 69 declared / 69 implemented, `missing: []`, `extra: []`** (regex-extracted every `method:`/`path:` pair from SCAFFOLD.yaml, normalized `{id}`<->`<var>`, diffed against Flask's `url_map`).
- Booted twice from clean processes via `PORT=... bash start.sh`; curled across resource families: `POST /_clock/set_current_utc` -> `{"current_utc":"2026-08-01T00:00:00.000Z"}`; `GET /bridges` empty list envelope with `limit/offset/total_count/has_more`; `POST /personnel` 201 (`qualification_status: CURRENT` derived); `POST /bridges` 201 with all derived fields (`min_nbi_rating 7`, `inspection_interval_months 48`, `underwater_interval_months 60`, due dates `2030-08-01`/`2031-08-01`); `GET /bridges/{id}/compliance-summary` 200; `POST /program-cycles` 201 (reserve 500000000 / available 9500000000); `POST /permit-applications` 201 (`gross_weight_tons 39.6`, `axle_count 5`). Error envelopes: 401 `ERR_UNAUTHENTICATED`, 403 `ERR_ROLE_NOT_PERMITTED`, 404 `ERR_BRIDGE_NOT_FOUND`, 400 `ERR_INVALID_REQUEST` (bad `limit`), 404 `ERR_INSPECTION_RECORD_NOT_FOUND`.
- Full ~60-call end-to-end script (`/tmp/t2537_smoke.py`) printed **ALL SMOKE CHECKS PASSED** against a fresh boot. Every PRD worked example reproduces exactly: rating factors 0.618/0.477, tons 22.2/17.2, posted limit 17.0, phi_c 0.85, element health indices 75.0 / 46.67, BHI 67.95, deficiency 49.72 %, priority score 42.64, cost 24,955,000 cents, compliance 100.0, `identity_holds true`. All cascades verified (acceptance 5-hop, close -> permit revocation, scour finalize -> auto POA + interval 12, POA approve -> `poa_compliant`, resolve -> POSTED fallback, federal ACCEPT -> cycle CLOSED).
- **Per-test-server safety confirmed empirically**: created a bridge and moved the clock to 2030, killed the process, relaunched — `bridges total_count 0`, `personnel total 0`, clock back to `2026-08-01T00:00:00.000Z`. Storage is Python dicts only; no SQLite/JSON/tmp artifacts (directory listing shows only source files).
- Server killed; `ss -ltn` confirms no listener on the test ports.

## Judgement call worth flagging
`next_inspection_due_date` / `next_underwater_due_date` are emitted **date-only** (`"2030-08-01"`). SCAFFOLD's Bridge entity table types them `datetime`, but the derived-field spec (SCAFFOLD.yaml:2087-2107) returns a Python `date` with precision "Whole calendar dates, UTC", and the compliance-summary output block (SCAFFOLD.yaml:2873) types the same two fields `date`. I kept date-only so both reads agree. `last_routine_inspection_date` / `last_underwater_inspection_date` remain the client's `inspection_date` string echoed verbatim (a full datetime), per PRD §3 hop 3.

## Step 5: Generate unit tests — 2026-09-03T11:42:00.000Z

Stage 2 is complete. Final state of the two generated directories:

**`test_suite/` — 223 tests, all collecting**

New this session:
- `test_30_role_boundaries.py` (597 lines, 10 tests) — finished with the eight-call cross-role 403 sweep (`cross_role_exclusive_operations_returns_403`, 2 tests) and the two duty separations (`segregation_of_duties_blocks_self_review_and_own_finding_authority_returns_403`, 3 tests: submitter-self-review, team-leader-authorising-its-own-closure, and the unrelated reviewer accepting afterwards).
- `test_31_optimistic_concurrency.py` (357 lines, 6 tests) — both §2.9 version guards: stale `expected_bridge_version` after an acceptance cascade (3 tests, incl. the worked rating case phi_c 0.85 / 0.618 / 22.2 / 0.477 / 17.2 / limit 17.0 and the "version a successful create consumed is itself stale") and stale `expected_program_cycle_version` (3 tests, incl. supersede of the cascade's AUTO candidate and precedence over both `ERR_BRIDGE_NOT_INSPECTED` and `ERR_PROGRAM_STATE_INVALID`).
- `test_32_aggregate_reconciliation_and_visibility.py` (305 lines, 5 tests) — rollup-vs-row reconciliation across a DRAFT redistribution (78.00 EHI, 1308/402/19 fixed, bridge 30.73 / BHI 63.87) and the immediate-consistency instance (scour code 2 finalisation visible to another role's very next `GET`, plus the cascade-made plan listable on the first call).

One design deviation, deliberate: the `candidate_create_against_stale_cycle_version` recipe advances the cycle version with a **lock/reopen pair**, but the PRD never says lock or reopen increments `ProgramCycle.version` (§3.8 lists version bumps only for candidate create/program/withdraw/defer). I realised the same 412 through a mechanism the PRD does state verbatim — acceptance-cascade hop 5 — and asserted nothing about lock/reopen and version.

**Verification (all run from the task directory)**
- `python3 -m py_compile test_helpers/*.py test_suite/*.py` -> OK for all 38 files.
- `python3 -m pyflakes` -> silent on every file.
- `python3 -m pytest --collect-only -q` -> **223 tests collected**, no collection errors.
- Coverage audit against both yamls: 103 instances parsed, 23 `excluded_because:` stubs — every non-stub queue-A instance (18) carries >=2 tagged tests, every non-stub queue-B instance (62) carries >=1, no stub is tagged, and no `Design:` tag points at a non-existent instance. All 223 tests carry exactly one tag, as the docstring's last line.
- Verbatim-citation audit: 479 PRD quotes across the suite, `MISSING_COUNT 0`, `NO_CITATION_COUNT 0`.
- Section-label audit over `test_suite/` **and** `test_helpers/`: `SECTION_ISSUES 0` — this caught three quotes in `test_helpers/assertions.py` that had dropped the PRD's markdown emphasis (`**cents**`, `**down**`, `*downward*`); fixed in place.
- No reference to "scaffold", `§1.x`, or the yaml design files anywhere in generated code. `__pycache__`/`.pytest_cache` removed.

Per-file line counts are in the `wc -l` block above; totals are `test_helpers/` 3311 lines over 9 files and `test_suite/` 10467 lines over 30 files (13778 combined). The `workspace/implementation/` directory was never read or written, and no sibling task directory was opened.

## Step 7: Run tests and iterate — 2026-09-03T12:10:00.000Z

Clean 8-round sweep achieved.

## Summary

**Iterations run:** 2 (sweep -> 2 test fixes -> sweep).

**Iteration 1 result:** 221/223 in every one of the 8 rounds — the *same* 2 tests failed deterministically in all 8 rounds (no flakiness, no load-induced timeouts, no reaping: `setsid` held).

**Tests deleted:** none. Both failures survived STEP 1a (PRD verbatim-covers) and STEP 1b (unique derivability), and both turned out to be STEP 2 test bugs — the test setup did not express the PRD rule the assertion checks.

**Fixes applied to `test_suite/`:**

1. `test_suite/test_25_endpoint_surface.py` — helper `_one_analysed_route_the_analysis_denied()` now calls `fx.pin_base_clock(client)` first.
   *Why:* `test_the_matching_denial_lands_and_is_terminal` asserted `decided_at == c.BASE_CLOCK` (`2026-09-01T00:00:00Z`) but the test only used the bare `client` fixture, so the clock was never moved off the PRD §2.4 startup default. The server correctly stamped `2026-08-01T00:00:00.000Z` ("stamps `decided_at` from the logical clock", §3.7). The setup, not the implementation, was wrong.

2. `test_suite/test_31_optimistic_concurrency.py` — `test_the_stale_structure_version_is_reported_before_the_source_report_is_judged` now builds its non-accepted source report with `fx.draft_report_with_baseline(...)` instead of a bare `fx.open_inspection(...)`.
   *Why:* the empty DRAFT report violated **two** rules on the second (version-repaired) call, and §2.8 evaluates *17. Element-group coverage -> `ERR_ELEMENT_GROUP_MISSING`* **before** *27. Rating source acceptance -> `ERR_RATING_SOURCE_NOT_ACCEPTED`*. The implementation's `routes_ratings.py:91-94` orders those checks exactly as §2.8 requires, so `ERR_ELEMENT_GROUP_MISSING` was the PRD-correct answer. Giving the draft report a girder + bearing row satisfies §3.4's "That report must also carry at least one `SUPERSTRUCTURE` element row", leaving non-acceptance as the sole remaining fault — which is the rule the test is actually about. The exact-`error_id` assertion was kept, not relaxed.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none — no file under `workspace/implementation/` was modified (only runner-written `results.*.json`). The implementation was PRD-faithful on both counts.

**Final per-round table (iteration 2):** rounds 1-8 each 223 passed / 0 failed / 0 errors / 0 skipped / 223 total, ~403.4 s per round.

`ls -la` proof on disk: all eight `workspace/implementation/results.{1..8}.json` present, written Sep 3 12:03, ~66.6 KB each.

**One PRD inconsistency noticed but not acted on** (no test depends on it, so nothing failed): §2.8 check 3 states `reserve_pct` is "between 0.00 and 0.50 inclusive" while §3.8 constrains it "to the range 0.00 through 0.25 inclusive". A future test touching the 0.26-0.50 band would be non-uniquely-derivable and should be deleted rather than adjudicated.

**Orchestrator independent verification of the sweep artifacts** (guarding the known failure mode where a Step 7 subagent claims a clean sweep with no results files on disk): re-ran `ls -la results.*.json` and parsed all eight JSON files myself. All 8 exist and each reports `passed 223 / failed 0 / errors 0 / skipped 0 / total 223`. Confirmed genuine.

**Step 8 decision:** NOT skipped. The skip condition requires 0 deletions AND 0 `test_suite/` fixes AND 0 `test_helpers/` fixes AND 0 `implementation/` fixes; Step 7 applied 2 `test_suite/` fixes, so Step 8 runs with those two items as its `<step_7_diff>` focus list.

## Step 8: Finalize PRD — 2026-09-03T12:10:14.616Z

`PRD_FINALIZED.md` produced. **One edit total.**

## Line counts
- `PRD.md`: 560 lines
- `PRD_FINALIZED.md`: 560 lines
- Delta: 0 lines added/removed; 1 line changed in place (0.18% of lines touched, 0.00% line-count delta)

## Changes
- **§3.8 "Opening a cycle."** — revise — `reserve_pct` upper bound corrected from "0.00 through 0.25 inclusive" to "0.00 through 0.50 inclusive", resolving the §2.8/§3.8 internal contradiction the way the implementation resolves it — `implementation/routes_program.py:45-51` (`params.get_number(..., minimum=D("0.00"), maximum=D("0.50"))`, inclusive per `implementation/params.py:141-145`).

§2.8 check 3 ("between 0.00 and 0.50 inclusive") was already impl-accurate and was left verbatim.

## Pre-edit search log

**Edit 1 — §3.8 `reserve_pct` range**
- (a) **Subject:** the accepted numeric range, inclusivity and default of `reserve_pct` at program-cycle creation, plus anything downstream that could re-derive or re-validate it.
- (b) **Impl paths enumerated** (`grep -rn "reserve_pct\|reserve" implementation/ --include=*.py`, then read):
  - `routes_program.py:45-51` — the *only* validation/ingest site: `get_number` with `minimum=D("0.00")`, `maximum=D("0.50")`, `default=calc.DEFAULT_RESERVE_PCT`.
  - `implementation/params.py:78-96` + `141-149` (`get_number` / `_range_check`) — confirmed `minimum`/`maximum` are **inclusive** comparisons (`<` / `>`), so 0.00 and 0.50 both pass and 0.5000001 fails; this is what makes "inclusive" the right word.
  - `calc.py:462` — `DEFAULT_RESERVE_PCT = D("0.05")`, matching the PRD's stated default (left unchanged).
  - `calc.py:465-466` — `reserve_cents()` = round-half-up of `reserve_pct * authorized_budget_cents`; consistent with §3.8's existing "rounded half up" sentence, untouched by the range change.
  - `routes_program.py:53-74` — creation stores `reserve_cents`/`available_cents`/`remaining_cents` once; `routes_program.py:105-123` (allocation-summary) reads the *stored* `reserve_cents` and never re-derives it, so §3.8's "computed once, at creation, and never recomputed" stays true.
  - `serializers.py:226-228` — `reserve_pct` and `reserve_cents` are both serialized; `reserve_pct` is echoed exactly as supplied (no coercion/rounding), so no wording about the field's own precision was needed or implied.
  - Confirmed by grep that there is **no** cycle-update/PATCH endpoint and no second write path that sets or re-validates `reserve_pct`, so the single-site claim is safe and no parallel endpoint is mis-described.
- (c) **Wording adjustment:** none needed — the change was confined to the numeral `0.25` -> `0.50`, leaving "defaulting to 0.05", "inclusive", and the surrounding waterfall prose byte-identical, which keeps every enumerated path accurately described.

## Step 7 items that required no PRD edit
1. **`test_25_endpoint_surface.py` clock pin** — pure test-setup bug. §2.4 already mandates the `2026-08-01T00:00:00Z` startup default and §3.7 already says `decided_at` is stamped from the logical clock; the impl obeys both. Nothing was PRD-silent, so §2.4 / §3.7 / §3.5 hop-4 prose kept verbatim.
2. **`test_31_optimistic_concurrency.py` fixture change** — pure test-setup bug. §2.8 already pins check 17 (`ERR_ELEMENT_GROUP_MISSING`) ahead of check 27 (`ERR_RATING_SOURCE_NOT_ACCEPTED`), and `implementation/routes_ratings.py:90-93` evaluates them in exactly that order (superstructure-row check, then bridge-match/ACCEPTED check). §3.4's prose mentions the two rules in the opposite narrative order but makes no evaluation-order claim, so I deliberately left it verbatim rather than adding an ordering sentence that §2.8 already supplies.

Note from the subagent: it looked for `test_suite/`/`test_helpers/` inside `workspace/` and did not find them (they live at the task root, one level up), so it verified directly against `implementation/`. Since `implementation/` is the sole alignment target for this step, the conclusions are unaffected.

**Orchestrator verification:** `diff PRD.md PRD_FINALIZED.md` shows exactly one changed line — PRD.md:384, the §3.8 `reserve_pct` sentence, `0.25` -> `0.50`. The file is not a byte-identical copy; the edit is real and matches the reported scope.

**Step 9 plan:** per this host's known failure mode (a single Step 9 subagent producing a byte-identical PRD_COMPLETED.md because the scan never actually ran), Step 9 is executed as THREE sequential file-partitioned passes over `implementation/` (4036 lines / 17 modules), each pass editing `workspace/PRD_COMPLETED.md` in place and handing off to the next:
- Pass A — request/response plumbing + core & inspection routes: `app.py`, `middleware.py`, `response.py`, `params.py`, `errors.py`, `db.py`, `routes_core.py`, `routes_inspections.py`
- Pass B — findings, ratings, scour/POA, permits: `routes_findings.py`, `routes_ratings.py`, `routes_permits.py`
- Pass C — programming/federal + the shared computation layer: `routes_program.py`, `calc.py`, `serializers.py`, `services.py`

## Step 9: Complete PRD — 2026-09-03T13:02:00.000Z

Step 9 was run as THREE sequential file-partitioned passes over `implementation/`, each editing `workspace/PRD_COMPLETED.md` in place (orchestrator seeded it as a copy of `PRD_FINALIZED.md`, then each pass was forbidden from re-copying or wholesale-overwriting it). This guards the known failure mode where a single Step 9 subagent returns a byte-identical PRD_COMPLETED.md because the scan never actually ran.

### Pass A — app.py, middleware.py, response.py, params.py, errors.py, db.py, routes_core.py, routes_inspections.py
560 -> 564 lines; 122,614 -> 129,078 chars (+4 lines, +6,464 chars). 22 ambiguity-pins, 4 mismatch-revisions.

Mismatches fixed: §2.8 item 6 applies-to list omitted inspection submit (`routes_inspections.py:144-145,231-232`); §2.10 claimed the specialty certificate is tested wherever a team leader is named, but impl tests it only at submit (`routes_inspections.py:46-47` vs `152-155`); §3.2 asserted a universal well-formedness-before-path-existence precedence that the redistribute endpoint inverts (`routes_inspections.py:353-355`); §4 intro + §3.2 said 204 carries "an empty data object" when delete returns a completely empty body (`app.py:36-52`, `response.py:53-54`).

Notable ambiguity-pins: `api_request_id` shape `req_`+20 uppercase alphanumerics and `api_request_timestamp` read from the **logical** clock (`response.py:22-30`); header trimming and whitespace-only-as-absent (`middleware.py:42-53`); `version` starts at 1 (`db.py:89-99`); creation-timestamp ties break by insertion order (`db.py:111-113`); the global client-instant convention (offset-less as UTC, date-only as midnight, stored fields keep verbatim client text); `next_*_due_date` render as `YYYY-MM-DD`; element create/redistribute/delete bump the parent report's version; redistribute is a full replacement with omitted CS quantities read as 0; a `QaReviewer` with no roster entry fails `ERR_QA_REVIEWER_NOT_QUALIFIED` not 404; a returned report keeps its indices/ratings/BHI frozen; unknown path -> `ERR_BRIDGE_NOT_FOUND` 404 and undeclared method -> `ERR_INVALID_REQUEST` 400, neither authenticated first; exact filter sets for three §4 list rows.

### Pass B — routes_findings.py, routes_ratings.py, routes_permits.py
564 -> 564 lines; 129,078 -> 135,214 chars (+6,136 chars, all in-paragraph). 25 ambiguity-pins, 7 mismatch-revisions.

Mismatches fixed: §2.6 per-axle rounding read as if it renormalised the stored array (now scoped to the point of entry into the gross-weight sum; `axle_loads_tons` echoes unrounded) (`routes_permits.py:52-55,74`); §2.8 body-FK enumeration omitted `sealed_by_id` and step 5's applies-to omitted sealing (`routes_ratings.py:167`); §2.8 step 12 omitted scour-evaluation creation (`routes_ratings.py:249`); §3.5 described the report-belongs-to-structure check as part of the element-condition check when it is unconditional (`routes_findings.py:50-51`); §3.5 said `RESOLVED` blocks the whole notification chain when it blocks only the `BRIDGE_OWNER` tier (`routes_findings.py:167-174`); §3.6 hop 2 written as a blind write-through when `scour_status` is re-derived from the latest finalised evaluation (`services.latest_final_scour`).

Notable ambiguity-pins: both OCC version fields validated as non-negative integers under step 3, so malformed is 400 never 412; `ERR_ELEMENT_GROUP_MISSING` (17) beats `ERR_RATING_SOURCE_NOT_ACCEPTED` (27); rating rejection names no engineer so runs neither identity nor SoD test; `notify` answers 201 with the log entry, bumping only the finding's version; closure hop 3 retains the three permit factors and hop 4's recompute therefore ordinarily returns its existing value; reopening reinstates neither permits nor flipped analysis rows; omitted `foundation_type` stored null not `UNKNOWN`; finalize/submit take no body; POA PUT is a full replacement writing omitted `countermeasure_type` as `NONE`; one analysis row per `route_bridge_ids` **entry** so a repeated structure yields two counted rows; `governing_analysis_min_rf` null when no row produced a factor; exact filter sets for seven §4 list rows.

### Pass C — routes_program.py, calc.py, serializers.py, services.py
564 -> 566 lines; 135,214 -> 140,851 chars (+2 lines, +5,637 chars). 12 ambiguity-pins, 3 mismatch-revisions.

Mismatches fixed: §3.2 claimed a new report has "every derived condition field null" when impl seeds `qa_escalation_required` false, the three rollups 0 and `quantity_balanced` **true** (`routes_inspections.py:82-97`); §3.3 hop 3 said a non-`ROUTINE`/non-`UNDERWATER` acceptance moves neither due date when impl always re-derives both from the newly settled interval (`services.py:284-294,390-396`); §3.4's half-ton quantisation is a floor (downward along the number line), not truncation toward zero — divergent for a negative rating factor (`calc.py:301-304`).

Notable ambiguity-pins: the systematic read-shape contract — every read emits the type's complete declared field set, valueless fields present as JSON `null` never omitted, nothing outside the declared set (`serializers.py:290-294`); rollup refresh is a from-scratch idempotent recomputation so deleting the last row leaves a vacuous `quantity_balanced` true; governing-rating ordering's third rung (insertion order) and the no-governing-rating branch's `posting_required` false + three null fields; §3.5 hop 3's permit-analysis flip is unconditional so an already-`DENIED` row has `result_reason` overwritten and `version` advanced; the cascade-created plan's full initial record; `reserve_pct` echoed at the supplied value and `fiscal_year` not unique; "latest `ACCEPTED` inspection" pinned as `accepted_at` -> `created_at` -> insertion order, and a supplied `source_inspection_id` on the wrong structure fails `ERR_BRIDGE_NOT_INSPECTED` (step 33) not 404/409; withdrawal retains `programmed_at`; a deferral omitting `justification` retains the stored narrative; federal submission creation has no cycle state gate and no uniqueness constraint; resubmission resets only `rejection_reason_code`, leaving `reviewer_user_id`/`reviewed_at` from the prior rejection; filter sets for the three remaining §4 list rows.

### Aggregate
- `PRD.md` 560 lines / 122,614 chars -> `PRD_FINALIZED.md` 560 / 122,614 -> `PRD_COMPLETED.md` **566 lines / 140,851 chars** (+6 lines, **+18,237 chars**, +14.9% over PRD.md).
- Totals across the three passes: **59 ambiguity-pins, 14 mismatch-revisions** (73 edits), no new sections.

### Orchestrator verification (independent of the subagents)
- `diff PRD_FINALIZED.md PRD_COMPLETED.md` -> **63 changed lines**. PRD_COMPLETED.md is emphatically NOT a byte-identical copy; the scan genuinely ran in all three passes.
- Structure intact: 5 top-level sections + all subsections (28 headings), §4 endpoint table still **69** rows, §5 error table still **43** rows.
- File ends at a real boundary — the final `ERR_BRIDGE_NOT_INSPECTED | 422` row of the §5 table. No truncation.
- No re-sweep needed: Step 9 touched only `PRD_COMPLETED.md`; `implementation/` and the test artifacts are byte-unchanged since the clean 8/8 sweep, whose `results.{1..8}.json` remain on disk.

## PIPELINE COMPLETE — 2026-09-03T13:02:00.000Z

All nine steps executed. Final state: 223 tests, 8/8 stability rounds at 223/223, and `workspace/PRD_COMPLETED.md` written.
