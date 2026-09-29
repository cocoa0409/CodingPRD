# Worklog — task_2709_supplement_label_claim_notification_compliance

## Step 1: Create task directory — 2026-09-04T00:00:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2709_supplement_label_claim_notification_compliance` and its `workspace/` subdirectory. Index 2709 was pre-assigned by the invoking pipeline; no scan of ./tasks/ was performed (concurrent pipelines on this host).

## Scaffold generation complete (2026-09-04)
- SCAFFOLD.yaml: 11 entities, 10 state machines, 2 concurrency rules, 14 calculations, 52 validations, 59 endpoints, 56 errors, 6 roles.
- SCAFFOLD_DIFFICULTY_DESIGN.yaml: 9 rules x 2 instances = 18.
- SCAFFOLD_CORNER_DESIGN.yaml: 9 sections, 78 instances (54 with test_recipe, 24 excluded_because stubs).
- scaffold_lint.py: VERDICT: clean lint (600 calls scanned). Every one of the 56 error ids is referenced by at least one instance.

## Step 2: Generate scaffold (subagent) — 2026-09-04T10:34:00.000Z

Subagent summary (verbatim):

All three scaffold artifacts are complete and lint-clean in `/home/ubuntu/github/CodingPRD/tasks/task_2709_supplement_label_claim_notification_compliance/`.

**SCAFFOLD.yaml** (2771 lines, 153 KB) — `domain_name: supplement-label-claim-compliance`, `api_prefix: /supplement-compliance`; top-level keys only `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` (no design keys).
- 11 entities: Product, Ingredient, ProductIngredient, NDINotification, StructureFunctionClaim, SubstantiationDossier, LabelPanel, AdverseEventReport, Supplier, IngredientLot, CertificateOfAnalysis
- 10 state machines, 2 §1.2.1 concurrency rules (`panel-create-stale-product`, `dossier-create-stale-claim`)
- 14 calculations, 52 ordered validations (priorities 1–41), 59 endpoints (incl. a `_clock` test endpoint), 56 errors, 6 roles (segregation-of-duties model, one `entity_backed:Supplier` role)

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** (1595 lines) — single key `scaffold_difficulty_design`; all 9 §0.5 rules × 2 differentiated instances = **18 instances**, every literal (scores 34.80/66.00/78.00/90.00, indices 10/16/35/47/77, dates 2026-08-24 / 2026-10-15 / 2026-12-29, line budgets 8/20/24) hand-derived from the pinned formulas.

**SCAFFOLD_CORNER_DESIGN.yaml** (2733 lines) — single key `scaffold_corner_design`; **9 sections / 78 instances** (54 with full `test_recipe`, 24 `excluded_because` stubs citing §1.8 instances by name):
entities 8, state_machines 14, calculations 12, validations 12, endpoints 6, errors 14, rbac 6, cross_cutting_complexity_layers 5, consistency_model 1.

Verification:
- `scaffold_lint.py` → `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (600 calls scanned across 18 + 54 recipe-bearing instances)
- All 95 instance names unique across both design files; every `excluded_because.difficulty_instance` resolves to a real §1.8 instance name; **all 56 error ids** are referenced by at least one instance (verified programmatically).
- Fixes made this pass: three unresolvable capture JSONPaths (envelope `total_count` on a list read, and two cross-entity fields captured off an AdverseEventReport response), a stale stub reference to a renamed boundary instance, and one wrong Supplier initial-state literal (`PENDING_QUALIFICATION` → `UNQUALIFIED`).
- No sibling task directory was read at any point; the design came solely from the scenario text plus the skill spec and `references/claim-extraction-guide.md`.

Orchestrator verification: all three files parse as YAML; SCAFFOLD.yaml carries neither design key; each design file has exactly its single expected top-level key.

## Step 3: Copy shared files — 2026-09-04T10:54:00.000Z

Copied ./INSTRUCTION.md to workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD (subagent) — 2026-09-04T11:12:00.000Z

Subagent summary (verbatim):

PRD generation for task 2709 is complete.

**Output:** `workspace/PRD.md` — 431 lines, 105,301 bytes.

**Section list**
- `# Supplement Label Claim Compliance API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 10 domain-derived subsections: 2.1 Role-Based Access Control, 2.2 API Response Structure (verbatim contract block), 2.3 Pagination and List Filtering, 2.4 Resource Identity/Versioning/Audit Trail, 2.5 Logical Regulatory Clock and Calendar Arithmetic, 2.6 Optimistic Concurrency (panel/dossier stale-version guards), 2.7 Request Screening Order, 2.8 Numeric Precision/Rounding/Conserved Ledgers, 2.9 Compliance Risk Index and Label Posture Gate, 2.10 Segregation of Duties
- `## 3. Business Logic & Workflows` — 9 lifecycle-grouped subsections (ingredient monograph & eligibility; NDI notification & 75-day waiting period; product registration & supplement-facts lines; claim development, substantiation & revision loop; panel construction/validation/lock; go-to-market & 30-day claim notification window; supplier qualification, lot disposition & CoA review; adverse-event intake/triage/filing/retention; posture cascades, retraction & return to `OPEN`)
- `## 4. Endpoint Definitions` — status-code paragraph + 59-row routing table
- `## 5. Error Code Catalogue` — 56-row table

**Coverage audit (all mechanically verified against SCAFFOLD.yaml, not by eye)**
- Endpoints: 59 / 59 in the §4 table (`grep -c` on method-leading rows returned exactly 59); every operation is also narrated in §3 by transition/role/capability framing.
- Errors: 56 / 56 in §5, and **all 56 also appear in the §1–§3 prose** (zero errors introduced only by the catalogue).
- Validations: 52 / 52. The 17-rank screening ladder is in §2.7; every validation's `error_id`, condition and `applies_to` scope is prose-rendered. Numeric-constant sweep over all calculations + validations found 68 numeric literals, of which 59 real domain constants are all present; the 9 absent values (19, 21, 27, 32, 33, 36, 37, 38, 39) are validation *priority ordinals*, not domain constants — each of those nine rules' actual content (serving-size regex tokens `capsule`/`scoop`, `declared_warning_codes` subset check, 75-day `ACKNOWLEDGE`-only gate, `WITHDRAWN`-excluding claim-text uniqueness, `study_count` >= 1, 65.00 acceptance threshold, `revision_round` < 3, `audit_score` >= 70 on `QUALIFY`, `remediation_reference` on `REINSTATE`) is documented.
- Calculations: 14 / 14, including both dual-variant families with both branches (`screening_provisional` denominator 50 / peer-review unenforced vs. `competent_reliable_final` denominator 100 / peer-reviewed-only inclusion; `PRODUCT_LAUNCH_BASIS` vs. `CLAIM_ACTIVATION_BASIS`) and the pinned per-study round-then-sum order.
- State machines: 10 / 10, 48 transitions, all 41 distinct states named verbatim in prose (missing-state check returned empty).
- Enum vocabulary: all 83 enum values across all 11 entities appear in the prose.

**Hard Contract reports**
- **Contract 1 (Field-Name Coverage): PASS** — required set built mechanically from every entity field plus every endpoint request-body / query-param / path-param token = 133 tokens; backtick extraction over PRD.md shows **0 missing**.
- **Contract 2 (Rule Coverage): PASS** — both OCC rules with their 412 codes and rationale, all cross-entity cascades (lot recall <-> supplier `total_released_kg`, CoA reject <-> supplier rejection count <-> posture, claim withdrawal <-> product active-claim ledger, AE triage/filing <-> risk counters), all `applies_to` scopes, sibling-branch symmetry (ACKNOWLEDGE/OBJECT, ACCEPT/REJECT, serious/non-serious, QUALIFY/PROBATION/REINSTATE/DISQUALIFY), and field-level structured content (evidence study objects: `study_type`, `subject_count`, `dose_match`, `peer_reviewed`, `citation`).
- **Contract 3 (§3 Path Purity): PASS** — §3 spans lines 160–303 with 335 distinct backtick tokens; leading-slash tokens: 0; bare HTTP-method tokens: 0; method+path tokens: 0; tokens containing any `/`: 0.

**Tail integrity: confirmed.** The file's last line is the final row of the §5 error table — a real section boundary. No truncation mid-sentence, mid-table or mid-list, and no audit/contract footer leaked into the document.

**Withheld files honored:** `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced, and no sibling task directory was read.

**Scaffold contradictions adjudicated during drafting** (recorded so the implementer and any later step stay consistent): `revision_round` increments on resubmission per the state machine (not at reject time); lot recall zeroes `released_quantity_kg` and decrements supplier `total_released_kg` to preserve the mass identity (the endpoint text saying "unchanged" would break the stated invariant); `marketing_start_date` is accepted in the request but stored as the logical clock's UTC calendar date; `retention_until` is minted at intake and carried through both triage branches; CoA-reject effects are described as a set with posture recomputation last.

Orchestrator verification (truncation guard): independently ran `wc -l -c`, `tail -6`, and `grep -n '^#'` on PRD.md. 431 lines / 105301 bytes; last line is `| \`ERR_REVISION_LIMIT_EXCEEDED\` | 409 |`, a complete table row at a real section boundary; all 5 top-level sections plus 19 subsections present. NOT truncated — no regeneration needed.

## Step 5: Generate unit tests (subagent) — 2026-09-04T12:42:00.000Z

Subagent summary (verbatim):

Generation is complete. Both output directories sit at the task root; neither exists under `workspace/`.

Files created — `test_helpers/` 2,328 lines: `__init__.py` 45, `api_client.py` 457, `api_errors.py` 147, `assertions.py` 190, `constants.py` 274, `factories.py` 284, `fixtures.py` 635, `test_users.py` 101, `types.py` 195

`test_suite/` — 6,538 lines: `conftest.py` 85 · **Queue B (Corner):** `test_01_ingredient_eligibility_and_notifications.py` 337 (6 tests), `test_02_product_registration_and_panel_lines.py` 402 (8), `test_03_label_panel_composition.py` 617 (9), `test_04_claim_substantiation_and_notification.py` 849 (9), `test_05_supply_chain_quality.py` 633 (9), `test_06_adverse_events_and_risk_profile.py` 302 (5), `test_07_authorization_and_segregation_of_duties.py` 452 (8) · **Queue A (Difficulty):** `test_08_dual_variant_scoring_and_notification_windows.py` 350 (4), `test_09_combinatorial_panel_and_risk_formulas.py` 293 (4), `test_10_revision_loop_and_label_lock_cycle.py` 321 (4), `test_11_quality_and_regulatory_cascades.py` 390 (4), `test_12_validation_priority_conflicts.py` 304 (4), `test_13_deadline_and_buffer_boundaries.py` 287 (4), `test_14_cross_entity_state_gates.py` 303 (4), `test_15_temporal_window_occupancy.py` 289 (4), `test_16_compensating_ledgers.py` 324 (4)

Test counts — **Queue A (Difficulty, §1.8): 36 tests** covering all 18 instances, exactly 2 tests each. **Queue B (Corner, §1.9): 54 tests** covering all 54 non-stub instances, 1 test each. The 24 `excluded_because:` stubs (of 78 total corner instances) were not translated, as specified. **Total 90 tests.**

Instances skipped — **None.** Every non-stub instance in both indices passed the PRD-first two-condition filter and was translated. No `pytest.mark.skip/xfail` appears anywhere in the suite.

Tag verification — a script parsed every `Design:` line and cross-checked it against the `name:` keys in both design yamls: 90 tags for 90 `def test_` functions — one tag per test, none untagged, none dual-tagged, and zero tags pointing at a non-existent instance. Per-file `^def test_` counts equal per-file `Design:` counts for all 16 files.

Other checks run — `python3 -m py_compile` clean on all 26 generated `.py` files. AST unused-import check clean on every file. Every name imported from `test_helpers.*` resolves in the real module (0 problems). Every `api.<method>(...)` call in helpers and suite resolves on `SupplementComplianceClient` (56 distinct methods, 0 missing). `__pycache__`/`.pyc` artifacts removed; `workspace/` contains only `INSTRUCTION.md`, `PRD.md`, `implementation/` (never read or written).

Notes worth relaying — eleven yaml-vs-PRD conflicts were resolved PRD-first throughout, most consequentially: recall mass buckets follow PRD §3.7 (`rejected_quantity_kg` takes the full mass, `released_quantity_kg` -> 0.00) rather than the yaml's figures; the revision-loop cap needs four reject cycles to reach `revision_round == 3`; `HEALTHCARE_PROFESSIONAL`/`RASH`/`MILD_GI_UPSET`/`OTHER_DIETARY_SUBSTANCE` were mapped to the PRD's real enum values; and the `Product.version == 5` sub-assertion in the label-lock-cycle instance was dropped because the PRD does not uniquely derive it.

## Step 6: Generate implementation (subagent) — 2026-09-04T12:42:00.000Z

Launched CONCURRENTLY with Step 5 in a single assistant message (per skill requirement — gives the impl generator physical isolation from test_suite/, which did not exist when it started).

Subagent summary (verbatim):

Implementation complete and smoke-tested.

Modules (23 files, 3,632 lines) — support layer: `app.py` 68 (app factory, blueprint registration, `ApiError`/404/405/415/500 handlers, `PORT` entry point), `db.py` 134 (in-memory `Store` with 11 dicts, logical clock default `2026-08-01T00:00:00Z`, `base_fields`/`touch` version bumps at most once per row per request), `errors.py` 156 (`ApiError` + all 56 error-id constants, HTTP status map, default messages), `response.py` 98 (envelope `meta`/`response_type`/`data`, `req_`+20 alnum request id, pagination limit 1–100 default 10, offset >= 0, `page`/`page_size` ignored), `auth.py` 64 (`@endpoint(roles)` — screen 1 `ERR_UNAUTHENTICATED`, screen 2 `ERR_UNAUTHORIZED`), `validate.py` 235, `calc.py` 268 (all enums/constants and 14 calculations, Decimal + ROUND_HALF_UP), `serialize.py` 265 (11 resource serializers + `risk_profile` computed read), `cascade.py` 209 (derived supplier set, risk index, posture recomputation and the 6 posture transitions).

Routes (`routes/`): `helpers.py` 69, `ingredients.py` 159, `ndi.py` 158, `products.py` 161, `lines.py` 166, `claims.py` 287, `dossiers.py` 162, `panels.py` 312, `aers.py` 146, `suppliers.py` 117, `lots.py` 178, `coas.py` 168, `clock.py` 21, `__init__.py` 31.

Coverage — **Endpoints: 59/59** registered (verified by walking `app.url_map`) — ingredients 5, ndi-notifications 5, products 6, product-ingredients 5, claims 8, substantiation-dossiers 5, label-panels 6, adverse-event-reports 5, suppliers 4, ingredient-lots 5, coas 4, clock 1. **Errors: 56/56** — every declared id is both defined and raised somewhere. **Validations: all 41 SCAFFOLD priorities** wired in the pinned screening order (the finer-grained expansion of PRD §2.7's 17 ranks). **Calculations: 14/14** — scoring (both variants), %DV, DV coverage, line budget, required warnings, risk index, posture, NDI window, panel window occupancy, business-day due date, retention, notification due date/basis, lot mass invariant, CoA acceptability. **State machines: 10/10** — Product lifecycle + label posture (2 dimensions, 6 posture transitions with retraction/dismantle side effects), Ingredient, NDINotification, Claim (substantiation + notification), Dossier, LabelPanel, AER, Supplier, IngredientLot, CoA.

Smoke test (`PORT=18709`, killed by exact PID 653492; port confirmed free) — all 23 files `py_compile` clean. Five scripted flows passed: envelope/pagination shape correct, unauthenticated -> 401, `page=5` ignored; full happy path (ingredient determination -> line %DV 125 -> dossier evidence screening 48.00 -> final 44.40 with denom 100 + peer enforcement -> panel validate `panel_lines_required` 8 <= allowed 24, warnings sorted, DV coverage 125 -> lock -> start-marketing -> notify-fda); approval path with final 90.00 (`PRODUCT_LAUNCH_BASIS` due 2026-10-15, late notify -> index 25); cascades (supplier PROBATION -> product RESTRICTED, approved claim -> REVISION_REQUESTED with `requires_recheck`, `active_claim_count` 0, ACCEPTED dossier -> UNDER_REVIEW; DISQUALIFY -> FROZEN + panel SUPERSEDED; CoA REJECT four hops -> index 58, supplier PROBATION; lot release/recall ledger returns to exactly 0.00); edge cases (`ERR_NDI_WINDOW_OVERLAP`, `ERR_WAITING_PERIOD_NOT_ELAPSED` then ACKNOWLEDGE, `ERR_STALE_CLAIM_VERSION`/`ERR_STALE_PRODUCT_VERSION` 412 before the FROZEN gate, `ERR_DISCLAIMER_MISSING`, `ERR_DUPLICATE_CLAIM_TEXT`, `revision_round` incrementing only on resubmission, leap-day retention 2028-02-29 -> 2034-02-28, 15-business-day due 2028-03-21).

Storage is process-local dicts only; nothing is seeded, and no file/DB/cache is written.

Contradictions resolved in favour of the PRD: recall moves the full mass to `rejected_quantity_kg` with `released_quantity_kg` -> 0.00; `retention_until` is minted at intake; the CoA-reject cascade orders lot disposition before the supplier transition; `revision_round` increments only on the resubmission edge; FROZEN dismantles panels but does not itself retract claims (only OPEN->RESTRICTED does).

Orchestrator verification: `test_helpers/` and `test_suite/` are both at the task root with no strays under `workspace/`; 17 files in test_suite/ totalling 90 `def test_` functions; `workspace/implementation/start.sh` present.

## Step 7: Test/fix iteration loop — 2026-09-04

**Iterations run: 1.** Clean on the first 8-round parallel sweep; no fixes and no deletions were required.

Sweep shape: 8 concurrent `prd-bench-local-run` rounds under `setsid`, `--isolation per-test-server --timeout 120 --test-timeout 30`, results written to `workspace/implementation/results.1..8.json`. Each round ran ~160s wall.

Evidence (per `results.$i.json`, never from the interleaved `sweep.log`):

| round | passed / total | failed | errors | skipped | duration |
| --- | --- | --- | --- | --- | --- |
| 1 | 90 / 90 | 0 | 0 | 0 | 160.1s |
| 2 | 90 / 90 | 0 | 0 | 0 | 160.2s |
| 3 | 90 / 90 | 0 | 0 | 0 | 160.2s |
| 4 | 90 / 90 | 0 | 0 | 0 | 160.2s |
| 5 | 90 / 90 | 0 | 0 | 0 | 160.2s |
| 6 | 90 / 90 | 0 | 0 | 0 | 160.1s |
| 7 | 90 / 90 | 0 | 0 | 0 | 160.2s |
| 8 | 90 / 90 | 0 | 0 | 0 | 160.1s |

Authenticity checks run on the evidence rather than trusting the counters: all 8 rounds carry 90 per-test entries with 90 *distinct* names and byte-identical name sets, so no round silently collected a subset; `grep` for `pytest.mark.skip` / `xfail` / `skipif` across `test_suite/` and `test_helpers/` returns nothing, so the `skipped: 0` is real rather than a suppressed-test artifact; the suite's 90 `def test_` functions equal the 90 collected; and a grep of `implementation/` for `sqlite` / `open(` / `json.dump` / `/tmp` / `pickle` / `shelve` finds no file persistence, confirming storage is in-memory dicts only and per-test-server isolation wipes all state.

Tests deleted: none. Fixes to `test_helpers/`: none. Fixes to `implementation/`: none.

## Step 7: Run tests and iterate (subagent) — 2026-09-04T12:52:00.000Z

Subagent summary (verbatim):

Clean sweep on the first iteration — nothing needed fixing.

**Iterations run: 1.**

**Final sweep evidence** (from `workspace/implementation/results.$i.json`, never from the interleaved `sweep.log`):

| round | passed / total | failed | errors | skipped | duration |
| --- | --- | --- | --- | --- | --- |
| 1 | 90 / 90 | 0 | 0 | 0 | 160.1s |
| 2 | 90 / 90 | 0 | 0 | 0 | 160.2s |
| 3 | 90 / 90 | 0 | 0 | 0 | 160.2s |
| 4 | 90 / 90 | 0 | 0 | 0 | 160.2s |
| 5 | 90 / 90 | 0 | 0 | 0 | 160.2s |
| 6 | 90 / 90 | 0 | 0 | 0 | 160.1s |
| 7 | 90 / 90 | 0 | 0 | 0 | 160.2s |
| 8 | 90 / 90 | 0 | 0 | 0 | 160.1s |

All 8 rounds were launched concurrently under `setsid` with `--isolation per-test-server`, and every round ran to completion. Union of failing tests across all 8 rounds is empty, so there was no flakiness signal to chase and the diagnostic protocol never had to be entered.

**Tests deleted:** none.
**Fixes applied to `test_helpers/`:** none.
**Fixes applied to `implementation/`:** none.

**Because a first-iteration clean sweep is the shape a fabricated or degenerate run would also take, I verified the evidence rather than trusting the counters:**
- All 8 rounds carry 90 per-test entries with 90 *distinct* names and byte-identical name sets across rounds — no round silently collected a subset of the suite.
- `grep` for `pytest.mark.skip` / `xfail` / `skipif` across `test_suite/` and `test_helpers/` returns nothing, so `skipped: 0` is genuine and not a suppressed-test artifact.
- The suite's 90 `def test_` functions equal the 90 collected, so the runner saw the whole suite.
- `implementation/` has no `sqlite`, `open(`, `json.dump`, `/tmp`, `pickle`, or `shelve` — storage is in-memory dicts only, so `start.sh` re-invocation under per-test-server isolation wipes every byte of state and no round could have been passing on state leaked from a previous one.

Two notes for whoever picks this up next. The `~160s`-per-round wall time is uniform across all eight rounds, which is the signature of genuine parallel execution under CPU contention rather than of rounds short-circuiting. And because there were no failures, no interpretation decisions were made — no PRD-coverage or unique-derivability adjudication was needed, so the test artifact stands exactly as Step 5 generated it, and the eleven yaml-vs-PRD conflicts that Step 5 resolved PRD-first were not revisited.

**Orchestrator independent verification** (a subagent has previously been observed claiming a clean sweep while leaving no results files behind, so this was re-checked at the orchestrator level rather than trusted): `ls -la workspace/implementation/results.*.json` shows all 8 files present (~28.5 KB each, all timestamped 12:45), and re-parsing each with `json.load` gives `passed=90 total=90 failed=0 skipped=0`, 90 entries and 90 distinct test names per round. The sweep is real and green.

## Step 8: Finalize PRD — SKIPPED — 2026-09-04T12:56:00.000Z

Skip condition from the skill applies exactly: Step 7 exited on its FIRST 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — zero iterations beyond the baseline. `PRD.md` therefore already determined every behavior the implementation exhibits at every site the test suite exercised, and there is no `<step_7_diff>` to hand off. No subagent was spawned; `workspace/PRD_FINALIZED.md` is intentionally absent. Step 9 will consequently start from `workspace/PRD.md`.

Note that a skipped Step 8 does NOT mean the PRD is complete — it only means Step 7 produced no failure signal. Every PRD silence the implementation resolved at generation time without tripping a test remains, and Step 9's full impl scan is the only thing that closes those. Step 9 is therefore the load-bearing alignment step for this task.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch (3 sequential subagent passes) — 2026-09-04T14:05:00.000Z

Because Step 8 was skipped, the source was `workspace/PRD.md`. A single subagent has previously been observed producing a PRD_COMPLETED.md byte-identical to its source (i.e. the scan never actually ran) on a domain this size, so Step 9 was deliberately run as THREE SEQUENTIAL passes partitioned by implementation module, all editing one shared `workspace/PRD_COMPLETED.md` with targeted Edit calls. Pass 1 owned the `cp`; passes 2 and 3 were explicitly forbidden from copying so they could not clobber earlier work. Each pass was told which modules the others owned, so no two passes contended for the same paragraph subject.

Partition: pass 1 = support layer (app.py, db.py, errors.py, response.py, auth.py, validate.py, calc.py, serialize.py, cascade.py); pass 2 = routes/{helpers,__init__,clock,ingredients,ndi,products,lines,panels}.py; pass 3 = routes/{claims,dossiers,aers,suppliers,lots,coas}.py. Findings were handed forward between passes (pass 1 spotted a routes-owned §4 clock mismatch it could not fix in lane and passed it to pass 2; pass 2 certified the §2.7 ladder as a verified impl match and flagged `int_filters` as dead code, so pass 3 did not re-derive either).

### Pass 1 — support layer (verbatim summary)

`workspace/PRD_COMPLETED.md` created by `cp` from `workspace/PRD.md`. PRD.md untouched. All edits applied with targeted `Edit` string replacements.

PRD.md: **431 lines / 105,301 chars** -> PRD_COMPLETED.md: **431 lines / 112,112 chars** (**+6,811 chars**, line count unchanged — every edit is an in-paragraph insert/revision). **15 ambiguity-pins, 0 mismatch-revisions** (no place where PRD prose contradicted these modules; the impl's 56 error ids, their statuses, and even the catalogue's row *order* match `errors.py` exactly).

Changes: §2.1 insert ambiguity — "empty" means the literal empty string, header values never trimmed — `auth.py:41-44` · §2.2 insert — `api_request_id` is `req_` + exactly 20 chars from A–Z/0–9 — `response.py:21` · §2.2 insert — `api_request_timestamp` read from the **logical clock**, not host wall clock — `response.py:27` · §2.3 insert — out-of-range/non-integer `limit` and negative/non-integer `offset` are `ERR_VALIDATION` 422, `offset` >= `total_count` legal and yields empty array, empty-string params treated as omitted — `response.py:74-91` · §2.3 insert — `created_at` ties break by insertion order — `db.py:133` · §2.4 insert — `id` is canonical lower-case 36-char hyphenated UUID — `db.py:64` · §2.4 insert — **`version` advances at most once per row per request** regardless of cascade depth, while `updated_at` is restamped by each step — `db.py:112-116` · §2.5 insert — every collection empty at process start, nothing seeded — `db.py:36-40` · §2.5 insert — `current_utc` parse tolerance (trailing Z/z, offsets converted, offset-less read as UTC, unparseable -> `ERR_VALIDATION`), clock may move backwards — `validate.py:216-235` · §2.7 preamble insert — unknown path / undeclared method answered **before authentication**, carrying `ERR_VALIDATION` at HTTP 404/405 rather than its tabled 422; trailing slash not a route distinction — `app.py:21,30-40` · §2.7 rank 4 insert — body parsed as JSON regardless of `Content-Type`, absent body = `{}`, non-object body = `ERR_VALIDATION`, booleans never satisfy numeric fields, integer fields reject `30.0`, dates exactly 10 chars, string/FK-id fields must be JSON strings so they fail at rank 4 not 5 — `validate.py:16-23,38-44,112-213` · §2.8 insert — exact decimal arithmetic on the literal as written (`12.345`->`12.35`), scores/kg masses render as JSON numbers without trailing zeros — `calc.py:117-135`, `serialize.py:197,212` · §2.9 insert — derived supplier set dedupes, ordered by creation order of first contributing lot — `cascade.py:50-59` · §3.3 insert — exact `risk_profile` projection shape (no created_at/updated_at/version; product under both `id` and `product_id`; `base_score`; `escalation_surcharge`; supplier set duplicated under `derived_supplier_set` and `derived_supplier_ids`; plus `requires_label_revision`, `lifecycle_status`) — `serialize.py:248-265` · §3.5 insert — `declared_warning_codes` echoed exactly as submitted (order, duplicates), unlike the sorted `required_warning_codes` — `serialize.py:152` · §3.7 insert — `assay_percent_of_label` carried at 2dp and rendered as a **JSON string** (`"99.46"`), unlike kg masses — `serialize.py:234` · §3.9 insert — posture recomputation landing on the current value is a total no-op (no transition, no `requires_label_revision` rewrite, no `updated_at`/`version` bump) — `cascade.py:145-147` · §5 preamble insert — `message` is diagnostic and non-contractual, routing failures reuse `ERR_VALIDATION` at 404/405, internal failure is 500 `ERR_INTERNAL` with an **empty `meta`** — `app.py:48-58`

All claims smoke-tested against a live server on port 10731 (killed by exact PID, port freed). Deliberately left in lane: §4's "clock endpoint responds with 200 and an empty `data` object" is a mismatch (`routes/clock.py` returns `{"current_utc": ...}`) — handed to pass 2. One suspected rank-4/5 pin around `db.get`'s non-string guard was DROPPED after confirming every route resolves FK ids via `validate.req_str`/`opt_str` first, making the 404 path unreachable — chose not to assert something false. Tail intact.

### Pass 2 — ingredient/NDI/product/line/panel routes (verbatim summary)

431 lines (unchanged), **118,366 chars**, delta **+6,254** over the inherited 112,112. **17 edits: 7 mismatch-revisions and 10 ambiguity-pins.** Pass 1's work fully intact (all 15 sentinels verified, one hit each), `^#` header set byte-identical to baseline, tail at a real boundary.

Confirmed against a live server on port 41837, stopped by exact PID 1436133. Port 39471 was already occupied by a *different* pipeline's server and `ps` showed ~20 other `python3 app.py` processes on the host — no broad pattern kill was used.

Changes: §4 revise **mismatch** — clock returns `data: {current_utc: "...Z"}`, not an empty object (the pass-1 handoff, confirmed live) — `routes/clock.py:21` · §3.5 revise **mismatch** — the active-lines floor is the **last** screen, not the first; a no-lines product still reports `ERR_SERVING_SIZE_FORMAT_INVALID` first (§2.7 rank 17 already agreed with impl; §3.5 contradicted both) — `routes/panels.py:268` · §3.5 revise **mismatch** — panel lock has no product-lifecycle precondition; an already-`LABEL_LOCKED`/`MARKETED` product accepts a further lock and keeps its lifecycle; killed the false "move together or not at all"; zero active lines pass the eligibility gate vacuously and lock — `routes/panels.py:307` · §3.5 revise **mismatch** — the product's `version` advances on **every** panel creation, not only when superseding; a named panel still in `DRAFT` is left untouched — `routes/panels.py:122,115` · §3.2 revise **mismatch** — NDI drafting enforces no eligibility state at all (a package opens against a `GRANDFATHERED` ingredient: 201) — `routes/ndi.py:41` · §3.2 revise **mismatch** — the filing cascade fires only out of `NDI_REQUIRED` — `routes/ndi.py:109` · §3.2 revise **mismatch** — the `ACKNOWLEDGE`/`OBJECT` ingredient cascades fire only out of `NDI_PENDING` — `routes/ndi.py:144,152` · §3.2 insert — `agency_objection_reason` optional, never stored on an `ACKNOWLEDGE` — `routes/ndi.py:123` · §3.5 insert — panel amendment: only `disclaimer_text` nullable; `panel_format`/`product_id`/`supersedes_panel_id` not amendable — `routes/panels.py:150` · §3.5 insert — the date-pair check on amendment uses the **merged** pair; the collision check never re-runs on amendment — `routes/panels.py:170` · §3.3 insert — the parent-product state screen outranks the line's own `line_status` screen — `routes/lines.py:117,150` · §3.3 insert — all four pack facts non-nullable on PATCH — `routes/products.py:83` · §3.1 insert — `daily_intake_mg` must be >= 0 (exactly 0 accepted); §2.7 rank 4 had omitted it — `routes/ingredients.py:38` · §3.1 insert — `rdi_mg` strictly > 0 when supplied — `routes/ingredients.py:39` · §3.1 insert — all five amendable monograph fields nullable, `daily_intake_mg` included despite being required at registration — `routes/ingredients.py:94` · §3.6 insert — `marketing_start_date` required and date-validated, then discarded (supplied `2030-01-01` stored as `2026-08-01`) — `routes/products.py:115` · §2.3 insert — filters match by exact case-sensitive string equality, empty-string filter matches nothing (unlike an empty `limit`), never matches null; `is_serious` the sole boolean filter — `routes/helpers.py:44`

Notes handed to pass 3: the §2.7 screening order is a **perfect** match to impl across all eight of pass 2's modules (every rank-4/5/7/8/9/11/12/14/15/17 sequence lines up), so treat §2.7 as reliable and prefer revising the §3.x narrative on conflict. `int_filters` in `helpers.py` is dead code, never used by any callsite — do not pin any integer list filter.

### Pass 3 — claim/dossier/AER/supplier/lot/CoA routes + final integrity check (verbatim summary)

Smoke server (port 41877) terminated by exact PID, port confirmed closed.

Inherited 431 lines / 118,366 chars -> after pass 431 lines / **127,108 chars** (my delta **+8,742**). PRD.md baseline 431 / 105,301, so **PRD.md -> PRD_COMPLETED.md total is +0 lines / +21,807 chars**. **23 edits: 19 ambiguity-pins, 4 mismatch-revisions.** All in-paragraph; no line added or removed by any pass.

Changes: §3.4 insert — claim drafting opens `approved_by_user_id`/`approved_at`/`notification_due_date`/`notification_due_basis`/`notified_at`/`submission_reference`/`withdrawal_reason` all null — `routes/claims.py:60-80` · §3.4 insert — both amendable fields optional and non-nullable, a body supplying neither still advances `version`, no other attribute amendable, claim excluded from its own uniqueness comparison, uniqueness at rank 15 after the rank-9 state screen — `routes/claims.py:104-131` · §3.4 insert — dossier creation screens **no** claim state; a dossier may open against `UNDER_SUBSTANTIATION_REVIEW`/`APPROVED`/`WITHDRAWN` — `routes/dossiers.py:26-72` · §3.4 insert — `subject_count` integer >= 0 (0 legal, `30.0` and negatives rank-4 `ERR_VALIDATION`), stored study object carries exactly the five supplied fields — `routes/dossiers.py:93-113` · §3.4 insert **mismatch** — the revision-round cap is evaluated **last** of the five preconditions, not second: a `REVISION_REQUESTED` claim at round 3 with no ready draft dossier answers `ERR_DOSSIER_NOT_READY` — `routes/claims.py:159-171` · §3.4 insert — dossier `rejection_reason` optional/nullable, never required, never stored on an `ACCEPT` — `routes/dossiers.py:126,150-156` · §3.4 insert — the reject->claim cascade fires only from `UNDER_SUBSTANTIATION_REVIEW`; a dossier dragged back by §3.9 re-reviews without moving the claim's status or `version`, and an `ACCEPT` there leaves the claim in `REVISION_REQUESTED` — `routes/dossiers.py:157-160` · §3.4 revise — `withdrawal_reason` a string not checked for emptiness — `routes/claims.py:236` · §3.4 insert — withdrawal leaves the whole notification dimension untouched, so a claim withdrawn while `DUE` stays `DUE` and can never be filed — `routes/claims.py:241-252` · §3.6 revise **mismatch** — "the anchor is made once at `NOT_DUE -> DUE` and never re-evaluated" is false: approval on a `MARKETED` product writes `notification_status`/`_basis`/`_date` unconditionally, so a retracted-then-re-approved claim is pushed back to `DUE` with `CLAIM_ACTIVATION_BASIS` overriding any `PRODUCT_LAUNCH_BASIS` and a fresh due date, while `notified_at`/`submission_reference` survive — `routes/claims.py:218-227` · §3.7 insert — `country_code` unvalidated for length/case/membership; `audit_score` opens null when omitted or explicitly null — `routes/suppliers.py:37-57` · §3.7 insert — both companion inputs range-checked on every decision but only `QUALIFY` writes `audit_score` and only `REINSTATE` writes `remediation_reference`/resets the counter; everything else discarded — `routes/suppliers.py:107-113` · §3.7 insert — `quantity_kg` rounded half up to 2dp at intake and it is that figure the buckets move; intake screens neither supplier qualification nor ingredient eligibility and recomputes no posture — `routes/lots.py:98-117` · §3.7 insert — certificate intake screens no lot state (`RELEASED`/`RECALLED`/`REJECTED` all accepted) — `routes/coas.py:39-56` · §3.7 revise **mismatch** — the 95.0/120.0 bounds are tested against the **unrounded** supplied assay: `94.996` stores as `"95.00"` yet is unacceptable (verified live) — `routes/coas.py:64-69`, `calc.py:260-268` · §3.7 insert — CoA `rejection_reason` optional/nullable/never stored on `ACCEPT` — `routes/coas.py:100,125-127` · §3.7 insert — acceptance advances the lot's `version` on **every** acceptance, not only the first — `routes/coas.py:120-122` · §3.7 insert — release, like recall, recomputes `label_posture` on every product with an `ACTIVE` line on the ingredient; it cannot degrade on the new supplier's account but can clear a posture left stale by line removal — `routes/lots.py:156-158` · §3.7 insert — hop 2 leaves an already-`RECALLED`/`REJECTED` lot completely untouched while the other hops still run — `routes/coas.py:146-149` · §3.7 revise — hop 3 stamps `last_decision_at` when the standing moves and leaves it alone when it does not; hop 4 runs regardless and, running after hop 2, already sees the newly-`REJECTED` lot — `routes/coas.py:151-168` · §3.8 insert — outcome-code membership is part of the rank-4 screen (`ERR_VALIDATION` ahead of an unresolvable `product_id`, verified live), empty array legal, duplicates retained, `received_date` unbounded — `routes/aers.py:34-39` · §3.8 insert — only the literal `true` forces the serious branch; omitted defaults false, explicit `null` reads false, non-boolean is `ERR_VALIDATION` (verified live) — `routes/aers.py:87,93` · §2.9 revise **mismatch** — the posture-recomputation trigger enumeration omitted ingredient-lot release and recall — `routes/lots.py:156-158,175-177`

Whole-document integrity verification: 431 lines in both PRD.md and PRD_COMPLETED.md, `diff` reports 0 lines added and 0 removed. Heading `diff` empty — 33 headings, identical text and order, no section added/lost/renamed. §4 endpoint table 59 rows (matches baseline); §5 error catalogue 56 rows (matches baseline). Earlier passes intact — modified-line set spans 50 lines covering pass 1's §2.1–§2.9/§3.9/§5 lines and pass 2's §3.1/§3.2/§3.3/§3.5/§4 lines; 20 distinctive pass-1/pass-2 spot-probe phrases all returned hits. Pass 3's own 22 sentinel phrases all present exactly once (except the deliberately parallel "never stored on an `ACCEPT`", twice — dossier and CoA reviews). File ends at `| ERR_REVISION_LIMIT_EXCEEDED | 409 |` with a trailing newline — final row of the §5 table, a real section boundary.

### Step 9 aggregate + orchestrator verification

Totals across the three passes: **55 edits — 44 ambiguity-pins and 11 mismatch-revisions**; PRD.md 105,301 chars -> PRD_COMPLETED.md 127,108 chars (**+21,807 chars, +20.7%**) with the line count, heading set, 59-row endpoint table and 56-row error catalogue all preserved exactly.

Orchestrator checks run independently of the subagents: `PRD_COMPLETED.md` exists and `cmp` confirms it is **NOT** byte-identical to `PRD.md` (the degenerate-scan failure mode); `diff` shows 100 changed lines across 50 line positions; `diff` of the `^#` heading sets is empty; the tail is the complete final error-table row. Also confirmed that **no file under `workspace/implementation/`, `test_suite/`, or `test_helpers/` was modified after the 12:45 green sweep** — Step 9 touched documentation only, so the 8/8 x 90/90 sweep evidence in `results.{1..8}.json` remains valid for the artifact as shipped. No re-run was required.

Pipeline complete. Step 9 has written `workspace/PRD_COMPLETED.md`.
