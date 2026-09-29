# Worklog — task_2262_municipal_stormwater_permit_program

## Step 1: Create task directory — 2026-09-01T00:00:00.000Z

Created `tasks/task_2262_municipal_stormwater_permit_program/` and `tasks/task_2262_municipal_stormwater_permit_program/workspace/` (allocated name used verbatim; no index scan performed).

## Step 2: Generate scaffold — 2026-09-01T00:00:00.000Z

The three scaffold artifacts for task 2262 are complete and lint-clean.

## Files
- `/home/ubuntu/github/CodingPRD/tasks/task_2262_municipal_stormwater_permit_program/SCAFFOLD.yaml` (§1.0–§1.7, 3325 lines)
- `/home/ubuntu/github/CodingPRD/tasks/task_2262_municipal_stormwater_permit_program/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8 only, 2268 lines)
- `/home/ubuntu/github/CodingPRD/tasks/task_2262_municipal_stormwater_permit_program/SCAFFOLD_CORNER_DESIGN.yaml` (§1.9 only, 5757 lines)

File split honored: neither design key appears in `SCAFFOLD.yaml`.

## Scaffold surface
- **Entities (12):** PermitTerm, ControlMeasure, Outfall, OutfallObservation, IllicitDischargeCase, ConstructionSite, PostConstructionFacility, Inspection, EnforcementAction, StormwaterAccount, FeeCreditApplication, AnnualReport. Topology flat with polymorphic and cross-aggregate relationships.
- **State machines (13)**, parallel shape — ConstructionSite carries two independent dimensions (`plan_status` / `field_status`), Outfall carries `status` / `screening_status` / `tmdl_status`; cyclic ceilings on case reopen (3) and credit resubmit (2); self-loop enforcement ladder. Plus 3 `concurrency_rules` (2 × `ERR_ACCOUNT_VERSION_CONFLICT`, 1 × `ERR_PERMIT_TERM_VERSION_CONFLICT`, all 412).
- **Calculations (10):** tiered ERU utility fee (per-component cent rounding), dual-variant credit-adjusted net fee (INTERIM vs FINAL), dual-variant annual pollutant load, sweeping load-reduction credit, dry-weather screening result, weighted inspection deficiency score, enforcement penalty with escalation tiers, goal attainment with gate overrides, compliance posture census, annual report statistics.
- **Validations (30 rules, priorities 10→90)**, deliberate inversions: OCC (60) above all state/business rules, referential (50) above fiscal (85), cooling-off (80) above the penalty-decrease guard (85), plan-approval (75) above interval overlap (80).
- **Endpoints:** 66, all exercised by at least one design instance.
- **Errors:** 73 codes, every one reachable from a §1.8 or §1.9 instance.
- **RBAC:** 7 roles under `segregation_of_duties` — StormwaterProgramManager, IDDEInvestigator, ConstructionInspector, EnforcementOfficer, MunicipalOperationsSupervisor, UtilityBillingClerk, PropertyOwner (`identity: entity_backed:StormwaterAccount`). Three user-level chokepoints: self-validation, inspector-cannot-enforce, same-user certification.
- Difficulty level declared `expert_plus`.

## Design instance counts
- **§1.8: 26 instances** across all nine hard-reasoning rules (dual-variant 2, combinatorial formula 3, non-linear state machine 3, transitive cascade 3, priority-pair conflict 4, boundary precision 3, cross-entity state dependency 3, resource/temporal overlap 2, compensating invariant 3).
- **§1.9: 93 instances** — entities 11, state_machines 25, calculations 12, validations 19, endpoints 8, errors 2, rbac 4, cross_cutting_complexity_layers 11, consistency_model 1. Of these, 63 carry full `test_recipe` chains and 30 are `excluded_because` stubs, each citing an existing §1.8 instance name.
- 119 instance names total, all unique across the two files.

## Verification
`python3 skills/prd-bench-scaffold-generator/scaffold_lint.py tasks/task_2262_municipal_stormwater_permit_program/` → **VERDICT: clean lint** (1333 calls scanned, all conform to §1.5; all §1.1 FKs have reverse-reachability). Additional self-checks passed: no stub carries a `test_recipe`, every cited `difficulty_instance` resolves, all 73 error codes and all 66 endpoints are covered, and every numeric literal in the asserts was recomputed with `Decimal`/ROUND_HALF_UP before being written.

## Step 3: Copy shared files — 2026-09-01T00:00:00.000Z

Copied `INSTRUCTION.md` to `tasks/task_2262_municipal_stormwater_permit_program/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T00:00:00.000Z

PRD written to `workspace/PRD.md` — 497 lines, ~12,320 words, ending at §5 with no audit footer. Withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced, and no sibling task directory was read.

**Sections covered**

- §1 Introduction — 3 paragraphs (MS4 program context, the six minimum control measures, the two design commitments: derived posture and segregated duties).
- §2 Global Specifications — 11 subsections: 2.1 Actors/headers/RBAC (7 roles, `PropertyOwner` entity-backed identity vs. opaque operator identities), 2.2 API Response Structure (pasted verbatim from `section-2.2-response-structure.md`), 2.3 pagination + ordering + every list filter parameter, 2.4 common fields and the logical clock (initial `2026-08-01T00:00:00Z`, never wall-clock), 2.5 the full 21-tier validation precedence ladder, 2.6 the 3 OCC rules, 2.7 rounding/precision, 2.8 cascade chain + annual-report invalidation, 2.9 segregation of duties, 2.10 the three distinct interval conventions (symmetric 14-day screening buffer, closed-closed inspection periods, half-open sweeping runs), 2.11 nested-path left-to-right resolution.
- §3 Business Logic — 9 subsections (permit term/measure set; outfall inventory + dry-weather screening; IDDE case lifecycle; construction plan review vs. field condition; permanent controls + both deficiency-score branches; enforcement ladder + penalty ledger; sweeping + annual load assessment; utility fees + credit programme; annual reporting).
- §4 — 66-row endpoint table (Method, Path, Description, Authorized Role(s)).
- §5 — 73-row error catalogue.

**Coverage audit results (all mechanical, via `yaml` diff against SCAFFOLD.yaml)**

- **Contract 1 — Field-Name Coverage: PASS.** 204 required identifiers (175 entity field names across all 12 entities + 99 endpoint input identifiers, deduplicated, + 10 computed response-shape fields) — 0 missing, verified in two independent passes.
- **Contract 2 — Rule Coverage: PASS.** 13 state machines / 44 transitions with all state literals present; 0 missing enum literals across every entity enum; 10 calculations with every constant present literally (`9633`/`8207`/`6541` tier rates, `0.00220462`, `0.85`, penalty bases `25000`/`50000`/`100000`, multipliers `1.00`/`1.50`/`2.25`, surcharge rates `0.00`/`0.05`/`0.12`/`0.08`, score weights `8`/`22`/`34`, `1.20`, `+12`, `+15`, `+25`, caps `100`/`30`/`0.5000`, thresholds `70`/`75.00`/`100.00`/`1000`/`0.25`/`0.50`/`1.00`, `14`-day and `90`-day windows); 30 validations rendered as the ordered ladder with all 73 error IDs referenced in prose; 3 concurrency rules with their exact version-field names and 412 codes. §4 table matches the scaffold exactly: 66/66 paths, 0 missing, 0 extra, **0 role-set mismatches**. §5 matches exactly: 73/73 error IDs, **0 HTTP-status mismatches**.
- **Contract 3 — §3 Path Purity: PASS.** Zero literal paths and zero HTTP method tokens anywhere in §3. Also verified: no pseudocode operators (`>=`, `<=`, `!=`, `==`, `&&`, `||`) anywhere in the document, and no fuzzy-language markers.

Two audit-driven repairs were applied: the `parcel_class` surcharge rates were restated as explicit decimals (`0.08` for `INSTITUTIONAL` had been prose-only), and `current_utc` was moved out of a JSON snippet into backticked prose.

## Step 5: Generate unit tests — 2026-09-01T00:00:00.000Z

The suite is complete. Final file written: `test_suite/test_31_version_gates_thresholds_and_immediate_cascades.py` (22 tests) closing the last five queue B instances — the four `cross_cutting_complexity_layers` instances (stale account version on remeasurement; credit application against a superseded snapshot; strict open-case gate vs inclusive enforcement gate; outfall retirement withdrawing lane miles from the measure only) and the single `consistency_model` instance (every cascaded field already correct in the writing call's own response).

Deliverables

- `test_helpers/` — nine modules (Stage 1, self-check `ok 73`): `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`, `__init__.py`.
- `test_suite/` — `conftest.py` + 31 numbered test files, **364 test functions** (406 collected items once parametrisation expands).
  - Queue A (§1.8, `test_01`–`test_12`): **103 tests**.
  - Queue B (§1.9, `test_13`–`test_31`): **261 tests**.

Coverage audit (script at `/tmp/design_audit.py`)

- Difficulty index: 26 instances, 0 stubs — every one has >=2 tests (minimum satisfied everywhere).
- Corner index: 93 instances = 63 real + 30 `excluded_because` stubs — **all 63 real instances have >=1 test**; per section: entities 10, state_machines 25, calculations 4, validations 9, endpoints 4, errors 2, rbac 4, cross_cutting 4, consistency_model 1.
- Design tags: 0 problems — every test has exactly one `Design:` line, it is the last docstring line, and no tag is malformed, dangling, or pointed at a stub.

Citation audit (`/tmp/prd_quote_check2.py`, the corrected v2): **536 citations checked, 0 non-verbatim** — every quoted span in every docstring appears verbatim in `workspace/PRD.md`.

Instances not translated / assertions dropped

- The 30 corner stubs carrying `excluded_because` were deliberately not translated (per spec they are not test sources). No real instance was skipped under the PRD-first filter this session.
- One sub-assertion from the consistency_model recipe was dropped: the PRD nowhere states a new illicit-discharge case starts with `tracing_attempt_count` at 0 (only §3.3's "increments `tracing_attempt_count` by one" on tracing/reopen), so that value is not asserted; the instance is still covered by the `OPEN` status, `origin_observation_id` and `opened_at` assertions.
- Also noted while writing test_31: the design's `applicant_user_id owner-01` is inconsistent with PRD line 29 (a `PropertyOwner`'s `X-User-ID` *is* the account id), so the test asserts `applicant_user_id == account["id"]`.

Everything compiles (`compileall` clean, `__pycache__` removed) and collects under pytest without touching the implementation directory or any sibling task.

## Step 6: Generate implementation — 2026-09-01T00:00:00.000Z

The implementation is complete and verified.

## Files created — `workspace/implementation/` (28 files)

**Root**
- `app.py` — app factory, blueprint registration under `/stormwater` (clock blueprint at root), `ApiError`/`HTTPException`/`Exception` handlers emitting the error envelope, `before_request` seeding `g.touched_rows`, `app.run(host="0.0.0.0", port=$PORT|10000)`
- `db.py` — logical clock (epoch `2026-08-01T00:00:00Z`, never wall-clock), 12 in-memory dicts keyed by id, `new_row`/`touch`/`_mark` (one version bump per row per request), `serialize`, `rows_sorted`
- `middleware.py` — identity/role gate (401 only on missing `X-User-ID`; 403 on missing/unlisted role), typed body coercers returning `Decimal`, pagination, filter validation
- `response.py` — success/list/error envelopes (`req_` + 20 alnum, millisecond `api_request_timestamp`)
- `errors.py` — full 73-code catalogue with statuses; `enums.py`; `requirements.txt` (flask); `start.sh` (`set -euo pipefail`, `cd $(dirname $0)`, guarded flask install, `exec python3 app.py`)

**`routes/` (13 modules + `common.py`)** — `permit_terms, control_measures, outfalls, observations, cases, construction_sites, facilities, inspections, enforcement_actions, accounts, credit_applications, annual_reports, clock`. `common.py` centralises 404 mapping, `require_active`, and the `settle()` recompute + report-invalidation cascade.

**`services/`** — `calc.py` (all 12 frozen calculations, `Decimal` + `ROUND_HALF_UP`, integer cents), `derive.py` (whole-term recomputation and report invalidation), `enforce.py` (shared issuance/penalty ledger), `report.py` (the 13 annual-report statistics).

## Verification

- **66/66 endpoints** implemented — a mechanical diff of `app.url_map` against every `method`/`path` pair in `SCAFFOLD.yaml` matched exactly, zero missing and zero extra (65 under `/stormwater` + `POST /_clock/set_current_utc`).
- **Role matrix: 0 failures across all 66 endpoints** — probed every endpoint with all 7 roles; every allowed role passes the gate and every disallowed role gets 403.
- **`start.sh` boots cleanly** from a fresh process (repeatedly killed and relaunched during testing); clock resets to `2026-08-01T00:00:00Z` and all 12 collections report `total_count 0` on every boot — nothing seeded.
- **End-to-end smoke run passes**: term -> 6 measures -> activation gate (`ERR_MEASURE_SET_INCOMPLETE`) -> outfall -> SUSPECT screening auto-opening a case -> trace/identify -> NOV `45000` -> cooling-off refusal -> escalation to `ADMINISTRATIVE_ORDER` `74000` with `prior_assessed_total_cents 0` (own row correctly excluded) -> case resolve reverting the outfall to `CLEAR` -> sample validate (self-validation blocked) -> sweeping overlap refusal -> PROVISIONAL vs FINAL load variants -> site plan/approve -> inspection `deficiency_score 70`, `escalation_triggered`, automatic `STOP_WORK` + auto-NOV `25000` -> facility agreement -> account `gross_billable_cents 27518` -> credit `0.2755` -> `UNDERFUNDED` + `AT_RISK` posture -> billing run -> both OCC conflicts (412) -> report window guard (422) -> compile -> `ERR_SAME_USER_CERTIFICATION` -> certify -> submit.
- **Storage is in-memory only**: greps confirm no `sqlite`, `open(`, `json.dump`, `pickle`, `shelve` or `/tmp` use anywhere; `start.sh` exports `PYTHONDONTWRITEBYTECODE=1` and the tree is left with no `__pycache__` or data artefacts.

Server processes started for testing were shut down; nothing is left listening.

## Step 7: Run tests and iterate — 2026-09-01T00:00:00.000Z

No stray servers (only my own grep matched), no disk persistence in the implementation, artifacts cleaned. The task directory is untracked as a whole, so all changes are contained.

## Summary

**Iterations run:** 2 sweeps (8 parallel rounds each). Sweep 1: 376/406 in all 8 rounds, 30 failing tests — all deterministic (each failed in all 8 rounds; no flakiness surfaced). Sweep 2: **405/405 passing in all 8 rounds, union of failures empty.**

The 30 failures collapsed into 5 root causes, only one of which was a genuine PRD-coverage problem.

**Tests deleted (1)**
- `test_23_request_layer_precedence.py::TestAnUnidentifiedCallerIsAnsweredFirst::test_03_an_unknown_actor_is_treated_as_no_actor_at_all` — **unique-derivability collapse (silent-roster / enum-membership-only pattern)**. The test asserts `ERR_MISSING_USER_ID` for `X-User-ID: nobody-at-all` under an *operator* role. PRD §2.1 does say "If `X-User-ID` is absent or does not name a known actor...", but the same paragraph also states verbatim that for the six operator roles "`X-User-ID` is an opaque operator identifier **not tied to any persisted entity**" and the server "**never compares it to any entity's `id`**". The PRD never enumerates a single operator identifier, offers no roster and no registration endpoint — so a faithful reader necessarily accepts any non-empty opaque operator ID, and satisfying the test would require hardcoding an actor roster at startup (forbidden by the no-seeding rule). Both readings are articulable, so the test goes. Scaffold rule that drove it: `Corner/validations/a_request_missing_x_user_header_is_rejected_ahead_of_role_and_shape` — still faithfully covered by the surviving `test_01`, `test_02`, `test_04` (genuinely absent header).

**Fixes applied to `test_helpers/` (3)**
- `factories.py` — `tmdl_permit_term_payload()`: routed its three TMDL defaults through `_merge` instead of passing them as explicit kwargs alongside `**overrides`. The old form raised `TypeError: got multiple values for keyword argument 'tmdl_wla_lb_per_year'` whenever a caller overrode a default, violating the module's own documented contract ("keyword overrides are merged over the defaults"). Unblocked 11 tests in test_04.
- `factories.py` — `suspect_screening_payload()`: same collision on the three indicator readings, fixed the same way. Unblocked 13 tests in test_08 and test_31.
- `fixtures.py` — `setup_tmdl_program()`: same latent collision on `outfall_codes`/`tmdl`; converted to `setdefault` so callers can override. Preventive, no test depended on it yet.

**Fixes applied to `test_suite/` (2)** — both cases where a fixture built a precondition that tripped a *higher-precedence* PRD rule than the one under test, masking the intended assertion:
- `test_15_case_machine_cycles_and_guards.py` — `TestQuietStatesAreBlockedByALiveAction.case_in_enforcement` called `setup_case_in_state(...)` on an outfall whose `suspect_outfall` fixture had *already* recorded a screening at the same instant, so setup recorded a second dry-weather screening 0 days later and the PRD-correct 14-day symmetric buffer (§2.10) rejected it with `ERR_SCREENING_INTERVAL_VIOLATION`. Now walks `suspect_outfall`'s existing case forward with `_trace`/`_identify`, matching the sibling `identified_case` fixture in the same file. This was also required for correctness, not just setup: `test_11` asserts `open_case_count == 0` after resolution, which only holds with exactly one case on the outfall.
- `test_14_term_and_inventory_lifecycle.py` — `test_09_expiry_is_refused_before_the_term_end` expected `ERR_TERM_END_NOT_REACHED` but its fixture also created a DRAFT annual report, so two guards were violated at once. Per §2.5 the open-reports guard is rung 13 and the term-end guard is rung 16, and "exactly one error is returned: the one belonging to the highest-precedence violated rule" — so the implementation's `ERR_OPEN_REPORTS_EXIST` was correct. Added a `program_without_report` fixture for that one test; `test_10`–`test_12` still use the open-report fixture they legitimately need.

**Fixes applied to `implementation/`:** none. No implementation change was warranted — every failure traced to a test-side bug or a non-derivable assertion, and in the two precedence/interval cases the implementation was already the PRD-faithful side.

Orchestrator verification: all 8 `results.{1..8}.json` report `passed == total == 405`.

## Step 8: Finalize PRD — 2026-09-01T00:00:00.000Z

`workspace/PRD_FINALIZED.md` created.

## Line counts
- `PRD.md`: 496 lines; `PRD_FINALIZED.md`: 496 lines; 2 lines revised (0 added / 0 removed) -> **0% line-count delta, 0.40% of lines touched**.

## Changes
- **§2.1 Actors, Headers and RBAC** — revise — replaced "absent or does not name a known actor" with "absent, or carries an empty or whitespace-only value ... every other value is taken at face value as naming the acting individual, with no roster lookup at this layer" — `implementation/middleware.py:33-35`.
- **§2.5 rung 1 (validation precedence ladder)** — revise — "A missing or **unknown**" -> "A missing, empty or whitespace-only" `X-User-ID` — `implementation/middleware.py:33-35`.

## Pre-edit search log (single subject, two sentence sites)
(a) **Subject:** what makes `X-User-ID` acceptable at the identification layer (rung 1 / `ERR_MISSING_USER_ID`), for all seven roles.

(b) **Impl paths enumerated:**
- `middleware.py:31-41` `require()` — the only identity gate: `ERR_MISSING_USER_ID` iff header is `None` or blank after `strip()`; no roster, no DB lookup, no registration table. Role check is a plain membership test against the endpoint's list.
- Grepped every `require(` callsite (60 sites across `routes/clock.py`, `permit_terms.py`, `control_measures.py`, `outfalls.py`, `observations.py`, `cases.py`, `construction_sites.py`, `facilities.py`, `inspections.py`, `enforcement_actions.py`, `accounts.py`, `credit_applications.py`, `annual_reports.py`) — confirmed **no** callsite performs any further actor-existence resolution on `X-User-ID`.
- Grepped every consumer of the acting id (`recorded_by_user_id`, `finalized_by_user_id`, `issued_by_user_id`, `reviewed_by_user_id`, `compiled_by_user_id`/`certified_by_user_id`, `applicant_user_id`) — all are *writes* of the opaque id or *comparisons against a field already stored on a row* (`observations.py:28`, `enforcement_actions.py:61`, `annual_reports.py:113`, `credit_applications.py:138`), never a roster membership test. Included the `PropertyOwner` surface (`accounts.py:56-59`, `credit_applications.py:59-73,126-151`): an owner id that matches no stored `StormwaterAccount` is not refused at identification; only `ERR_NOT_APPLICANT` can fire, and later.
- `routes/clock.py:15` — same `require()`, so the clock endpoint is covered by the identical rule.
- `services/enforce.py:38` `SYSTEM_USER_ID` — the auto-generated NOV's `issued_by_user_id` bypasses the header layer entirely; the new wording says nothing about it.

(c) **Wording adjustment made:** first draft said "never checks it against a roster of registered actors, so there is no separate 'unknown actor' rejection". That risked reading as a global claim covering the stored-identity comparisons of §2.9 and the `PropertyOwner` ownership language in §2.1's own next paragraph (which the impl honours only for `applicant_user_id`, and which is outside Step 7 scope). Re-scoped to "with no roster lookup **at this layer**", which constrains only rung 1 and leaves §2.9's three same-user checks and the `ERR_NOT_APPLICANT` ownership check untouched and unmentioned.

## Items judged to need no PRD edit
- **`test_helpers/factories.py` + `fixtures.py` kwarg-collision fixes (3)** — pure Python `TypeError` bugs in the helper's own `**overrides` plumbing; no behavioral claim about the server.
- **`test_15` screening-fixture rewrite** — `outfalls.py:159-167` implements exactly §2.10's symmetric, strict `< 14 days` buffer over every `DRY_WEATHER_SCREENING` at the outfall. PRD already unique; kept verbatim.
- **`test_14` `program_without_report` fixture** — `permit_terms.py:132-136` evaluates `ERR_OPEN_REPORTS_EXIST` before `ERR_TERM_END_NOT_REACHED`, matching §2.5's rung 13 < rung 16 plus the "exactly one error" rule. PRD already unique; kept verbatim.
- **No `implementation/` fixes were applied in Step 7**, so there is no impl-side change to back-propagate.

## Step 9: Complete PRD — 2026-09-01T00:00:00.000Z

`workspace/PRD_COMPLETED.md` is written and complete.

**Measurements**
- `PRD_FINALIZED.md`: 496 lines, 94,726 chars — `PRD_COMPLETED.md`: 496 lines, 100,657 chars (**delta +5,931 chars**, 0 lines added/removed).
- 37 source lines revised in place across 36 edits; `diff` of all `^#` headings is empty (no new sections, no reordering).
- **12 mismatch-revisions, 25 ambiguity-pins.**

**Changes** (`{section} — {kind} — {class} — {what} — {impl}`)

1. §2.1 — revise — mismatch — PropertyOwner ownership checks do not exist except the resubmission `applicant_user_id` test; account reads, credit-application reads/lists and new filings are role-only, so an owner reaches any account — `routes/credit_applications.py:139`, `routes/accounts.py:52`
2. §2.2 Success Format — revise — ambiguity — `api_request_timestamp` comes from the logical clock, not host time — `response.py:16`
3. §2.3 — revise — ambiguity — `created_at` ties (the norm under a logical clock) break by insertion sequence — `db.py:138`
4. §2.3 — revise — ambiguity — empty-string filter does not narrow; non-member enum filter is `ERR_VALIDATION` 400; id-valued filters accept any string — `middleware.py:260`
5. §2.4 — revise — mismatch — `created_at`/timestamps render 3 fractional digits only for non-zero milliseconds, else whole seconds — `db.py:43`
6. §2.4 — revise — mismatch — `version` bumps once per request, not per mutation; a row created and self-recomputed returns at 1 — `db.py:115,123`
7. §2.4 — insert — ambiguity — `to_iso8601` may carry any offset or none and is normalised to UTC like any body timestamp — `routes/clock.py:17`, `middleware.py:206`
8. §2.5 L3 — insert — ambiguity — unknown body fields ignored, explicit `null` treated as omitted — `middleware.py:65`
9. §2.8 — insert — mismatch — sole exception to "recomputation is a mutation": the facility inspection-currency block is rewritten (even on a plain read) without `updated_at`/`version`, and persists through a later refusal — `services/derive.py:175-199,390`
10. §2.8 — revise — mismatch — invalidating events are not five but every term-recomputing transition (adds sweeping run, case resolution, outfall retirement, `FINAL` load run, escalate/close/rescind); event instant is the observation's `observed_at`, else the clock — `services/derive.py:409`
11. §2.11 — revise — mismatch — parent existence precedes only *child-level* rules; the §2.5 shape layer (pagination/filters) still runs before the parent lookup — `routes/observations.py:30-45`
12. §3.1 — revise — ambiguity — `eru_sqft` and `funding_target_cents` are whole numbers; a fractional value is a shape failure — `routes/permit_terms.py:47,49`
13. §3.1 — revise — mismatch — a new measure is not asserted `PENDING`: registration runs the derivation, so a `MUNICIPAL_OPERATIONS` measure lacking both housekeeping flags is born `BEHIND` and bumps the term's counts — `services/derive.py:292-338`
14. §3.1 — revise — ambiguity — on expiry the open-report guard precedes the term-end test — `routes/permit_terms.py:134,136`
15. §3.2 — insert — ambiguity — `drainage_area_acres`, `baseline_concentration_mg_per_l`, `design_runoff_kl` and capacity stored at 2 dp — `routes/outfalls.py:62-64`
16. §3.2 — insert — ambiguity — sample readings stored at 2 dp while panel/load math uses the supplied values; "non-null value" qualifier on the panel inputs — `routes/observations.py`, `services/calc.py`
17. §3.2 — revise — mismatch — `last_screened_at` is the greatest `observed_at` among screenings (back-dating never lowers it); `open_case_count` counts non-`RESOLVED` cases term-wide — `services/derive.py:260-261`
18. §3.3 — revise — ambiguity — non-`RESOLVED` **and** non-null `responsible_party` both refuse with `ERR_CASE_INVALID_STATE`; an `ENFORCEMENT` case accepts further actions and stays put — `routes/enforcement_actions.py`
19. §3.4 — revise — mismatch — `submit-esc-plan` enters `ESC_REVIEW` from any status (including `ESC_REVIEW`/`APPROVED`), touches neither `field_status` nor `plan_review_round`, and makes the closure check its only state check; review reports `ERR_SITE_CLOSED` ahead of `ERR_PLAN_NOT_IN_REVIEW` — `routes/construction_sites.py:21,64,85`
20. §3.4 — revise — ambiguity — release reports `ERR_SITE_CLOSED` ahead of `ERR_SITE_NOT_STOPPED` — `routes/construction_sites.py:121-127`
21. §3.4 — revise — ambiguity — auto stop-work on an already-stopped site overwrites reason/`open_deficiency_score` but leaves `stop_work_count` — `services/enforce.py`, `routes/inspections.py:134+`
22. §3.4 — revise — ambiguity — closure refuses a stopped site with `ERR_SITE_NOT_ACTIVE_DISTURBANCE` and a closed one with `ERR_SITE_CLOSED` — `routes/construction_sites.py:142-148`
23. §3.5 — revise — ambiguity — `design_capacity_cf`/`service_area_sqft` stored at 2 dp — `routes/facilities.py:32`
24. §3.5 — revise — ambiguity — `months_since_last_inspection` is never negative and stays 0 with no inspection and no agreement — `services/derive.py:181`, `services/calc.py:293`
25. §3.5 — insert — ambiguity — a findings entry holds exactly `severity` and `description` — `routes/inspections.py:122`
26. §3.5 — revise — mismatch — `ERR_INSPECTION_NO_FINDINGS` precedes both subject-state tests, but `ERR_SITE_CLOSED` precedes all three — `routes/inspections.py:144-155`
27. §3.6 — revise — ambiguity — auto action's `issued_by_user_id` is the literal `system` — `services/enforce.py:8,38`
28. §3.6 — insert — ambiguity — `open_enforcement_count` counts `ISSUED`/`ESCALATED`/`CLOSED` site actions, so closing keeps it counted and only rescission removes it — `services/derive.py:285`
29. §3.7 — revise — ambiguity — `run_end_date` >= `run_start_date` and `lane_miles_swept` >= 0 are shape failures — `routes/outfalls.py:241-244`
30. §3.7 — revise — mismatch — the measure mirror only asserts itself once the term holds >=1 run (then overwrites on every recomputation); with no run a hand-reported actual stands — `services/derive.py:314-325`
31. §3.7 — revise — ambiguity — `reporting_year` is a whole number 1900–9999 — `routes/outfalls.py:284`
32. §3.8 — insert — ambiguity — `impervious_area_sqft` is a whole number — `routes/accounts.py:24,66`
33. §3.8 — insert — mismatch — term revenue/funding fields are rewritten only once the term has >=1 account; otherwise 0/`ADEQUATE` survive any `funding_target_cents` — `services/derive.py:341-375`
34. §3.8 — revise — ambiguity — credit-eligibility test precedes the ceiling test — `routes/credit_applications.py:102,108`
35. §3.8 — revise — ambiguity — the applicant test precedes the resubmission ceiling — `routes/credit_applications.py:139,141`
36. §3.9 — insert — mismatch — `swept_lane_miles` spans every outfall of the term, retired included — `services/report.py:100-105`
37. §3.9 — revise — ambiguity — the 90-day submission window is a whole-day test: any instant on day 90 is still in time — `routes/annual_reports.py:133-137`

Notable findings worth flagging: the facility inspection-currency block (#9) is a genuine breach of both the §2.5 atomicity rule and the §2.8 "recomputation is a mutation" rule — it mutates on GET and survives a rejected request; and §2.1's ownership regime and §2.8's "five events" list were the two places where the finalized PRD described behavior the implementation simply does not have.
