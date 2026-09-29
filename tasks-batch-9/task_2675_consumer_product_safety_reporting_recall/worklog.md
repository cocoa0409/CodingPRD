## Step 1: Create task directory — 2026-09-04T04:48:00.000Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2675_consumer_product_safety_reporting_recall and its workspace/ subdirectory. Index 2675 was pre-assigned by the orchestrating command; no scan of ./tasks/ was performed (concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-04T06:22:00.000Z

Scaffold generation for task 2675 is complete and lint-clean.

## Files

| Path | Lines |
|---|---|
| `SCAFFOLD.yaml` | 3642 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2423 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 6103 |

Each file ends at a real structural boundary (verified with `tail`); the two design files carry exactly one top-level key each (`scaffold_difficulty_design` / `scaffold_corner_design`), and `SCAFFOLD.yaml` carries neither.

## SCAFFOLD.yaml counts

- 13 entities, 63 endpoints, 7 roles
- 12 state machines / 57 transitions, 2 §1.2.1 concurrency rules (`pattern-create-stale-model`, `offer-create-stale-case`)
- 9 calculations, 34 validation priorities, 57 error codes
- complexity_profile: `compliance_audit` + `multi_party_negotiation`; layers `optimistic_concurrency`, `cascading_side_effects`, `dual_variant_calculation`, `rate_threshold_triggers`; consistency `immediate`

## Design index instance counts

`SCAFFOLD_DIFFICULTY_DESIGN.yaml` — **20 instances** over all 9 rule_ids, each >= 2: dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 2, transitive_cascade 2, priority_pair_validation_conflict 2, boundary_precision_check 3, cross_entity_state_dependency 2, resource_temporal_overlap 2, compensating_invariant 2.

`SCAFFOLD_CORNER_DESIGN.yaml` — **65 instances** across all 9 guide sections (57 full recipes + 8 `excluded_because` stubs): Entities 10, State Machines 11, Calculations 11, Validations 15, Endpoints 6, Errors 2, RBAC 4, Cross-Cutting Complexity Layers 5, Consistency Model 1.

## Lint verdict (verbatim, first and only run after the final append)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2675_consumer_product_safety_reporting_recall/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2675_consumer_product_safety_reporting_recall/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2675_consumer_product_safety_reporting_recall/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    63
  §1.1 entities declared:     13
  §1.8 instances scanned:     20
  §1.9 instances scanned:     57
  Calls scanned (§1.8+§1.9):  1638

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Additional self-checks (all passing)

- Zero unbound `${var}` across both design files (per-instance binding order, including `as_user_id:` and path templates); zero literal `expected_*_version` values; no extra keys on instances, recipes, or calls.
- All 8 `excluded_because` stubs omit `test_recipe` and cite a `difficulty_instance` that exists by name; zero duplicate names across the union of both files.
- All `grounds` references resolve to declared `entities` / `state_machines` / `calculations` / `validations[priority]` / `endpoints[METHOD path]` / `errors.ERR_*` elements.
- Error-code coverage: 57 of 57 declared codes are exercised by at least one design instance (the only unreferenced token is the `ERR_XXX` placeholder inside the §1.0 envelope example).

Two `SCAFFOLD.yaml` self-inconsistencies were repaired during the work: the `MONITORING -> CLOSED` transition was missing the ProductModel unfreeze side effect declared on `POST /recalls/{id}/close`, and 11 list endpoints declared `page?`/`page_size?` against the fixed §1.0 `limit`/`offset` envelope (fixed in the endpoint inputs and in the corner Listing instance's triggers/asserts).

## Step 3: Copy shared files — 2026-09-04T06:25:00.000Z

Copied ./INSTRUCTION.md to tasks/task_2675_consumer_product_safety_reporting_recall/workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T06:40:00.000Z

PRD generation is complete end-to-end.

**Output path:** `workspace/PRD.md` — **440 lines**

**Top-level sections present:** §1 Introduction; §2 Global Specifications & System-Wide Principles (2.1 RBAC, 2.2 API Response Structure, 2.3 Pagination, 2.4 Docket Records/Identifiers/Logical Clock, 2.5 Reading the Docket, 2.6 Numbers/Money/Rounding, 2.7 Optimistic Concurrency: Version Pinning, 2.8 Rule Evaluation Order and First-Failure, 2.9 Hazard Posture: Model-Level Containment Gate, 2.10 Segregation of Duties, 2.11 Cascades/Conserved Quantities/Compensating Actions); §3 Business Logic & Workflows (3.1–3.9); §4 Endpoint Definitions (all 63 endpoints); §5 Error Code Catalogue (all 57 errors).

**Tail confirmation (orchestrator-verified independently):** file ends on the last complete §5 table row `| ERR_EFFECTIVENESS_NOT_MET | 409 |`; no mid-sentence/mid-table truncation. All five `## ` headings present.

**Hard Contract reports (from generator, mechanically verified):**
- Contract 1 — Field-Name Coverage: PASS. All 138 scaffold identifiers appear verbatim in backticks. The two extraction hits absent (`preview`, `accepted`) are `calculations[].variants[].name` values, not field names; both are discussed by name in §3.9 prose.
- Contract 2 — Rule Coverage: PASS. All 57 error IDs explained in §1–§4 prose (not merely listed in §5); all 37 numeric constants present; all 96 enum values in backticks; all 34 priority-ordered validations narrated in §2.8; both concurrency rules in §2.7 with exact 412 error IDs; all 9 calculations reconstructable in prose including both variants of the four dual-variant ones (`hazard_pattern_risk_index`, `recall_effectiveness_rate`, `consent_agreement_total`, fixed/priced split in `remedy_reimbursement_total`); both conserved invariants and both deep cascades (`plan_approval_stop_sale` depth 3, `claim_fulfilment_credit` depth 4) given link-by-link with exact compensations. No pseudocode, no fuzzy quantifiers.
- Contract 3 — §3 Path Purity: PASS. Zero paths/HTTP methods in §3's 139 lines.

**Constraints honoured:** neither design index was opened, grepped, or referenced. Built incrementally (small Write + heredoc appends), so no 64k truncation.

**Scaffold inconsistencies the generator resolved by majority vote across the scaffold's own sources** (flagged for the test generator, since the alternate reading yields different asserts): `Retailer.delinquent_count` monotonic, never decremented; retailer `compliance_posture` returns to `CLEAR` purely on `open_stop_sale_count` reaching 0; hazard-pattern adjudication does not move `ProductModel.hazard_posture`, and `decision == SUPERSEDED` is `ERR_INVALID_REQUEST`; civil-penalty-case creation accepts a `SectionReport` in `{SUBMITTED, ACCEPTED, RETURNED_FOR_INFO}`; progress-report creation accepts a recall in `{APPROVED, MONITORING}`; accepting a progress report sets `SHORTFALL` only on `assessment == CRITICAL`; `consent_agreement_preview_cents` keyed on the standing offer when one exists else on `assessed_penalty_cents`; `cooperation_credit_cents` starts null; `ERR_UNITS_OUTSTANDING_EXCEEDED` re-checked at claim approval as well as creation.


## Step 5 — unit test infrastructure (in progress)

- Stage 1 complete: `test_helpers/` written at the task root (constants, types,
  api_errors, test_users, api_client, factories, assertions, fixtures, barrel
  `__init__`). 2427 lines. Barrel imports verified.
- `test_suite/conftest.py` written; exemplar `test_suite/test_01_dual_variant_calc.py`
  written (queue A rule `dual_variant_calc`, 4 tests).
- Remaining queue A rules and all queue B sections delegated to eleven
  file-disjoint generator agents.
- PRD-first filter casualty recorded: queue A
  `cross_entity_state_dependency/progress_report_creation_blocked_by_recall_not_yet_monitoring`
  is SKIPPED — it asserts a 409 for a progress report opened on an `APPROVED`
  recall, but PRD §3.8 permits exactly that, so the PRD does not uniquely derive
  the asserted refusal.

### Step 5 — unit test infrastructure (complete)

**Stage 1 — `test_helpers/` (9 modules, 2427 lines).** `constants.py`, `types.py`,
`api_errors.py` (57 error ids + HTTP status map, registered with the framework's
`set_error_http_status_map`), `test_users.py` (two holders per role plus retailer-rep header
builder), `api_client.py` (one method per declared endpoint, 63 verbs), `factories.py`
(21 payload builders), `assertions.py` (17 domain assertions), `fixtures.py` (the canonical
docket chain plus 14 `*_env` composites), `__init__.py` barrel.

**Stage 2 — `test_suite/` (19 files + conftest, 9876 lines, 204 tests).**
Queue A (`test_01`–`test_09`, 45 tests) covers 19 of the 20 difficulty instances, at least two
tests each. Queue B (`test_10`–`test_19`, 159 tests) covers all 57 non-stub corner instances;
the 8 `excluded_because:` stubs were not translated.

**Only PRD-first-filter casualty:**
`cross_entity_state_dependency/progress_report_creation_blocked_by_recall_not_yet_monitoring`.
The instance asserts 409 `ERR_RECALL_PLAN_STATE_INVALID` for a progress report opened against an
`APPROVED` recall, but §3.8 states a report is opened "against a recall whose `plan_status` is
`APPROVED` or `MONITORING`" — the contract contradicts the asserted outcome instead of uniquely
deriving it, so the instance was dropped with no placeholder and its sibling took a third test.

**Verification.** `python3 -m py_compile` clean on all 28 generated modules; `pyflakes` clean on
`test_suite/`; `pytest --collect-only` collects 204 tests with no import or duplicate-name
errors; an AST audit confirms every test carries exactly one `Design:` line as its docstring's
last line and that all 204 tags resolve to a real non-stub instance name in the two design
indices. Nothing was written under `workspace/`.

## Step 5: Generate unit tests — 2026-09-04T07:20:00.000Z

Test infrastructure for task 2675 is complete and verified.

**Files written — `test_helpers/` — 9 modules, 2427 lines**: `constants.py` 91 (severity/channel weight tables, exposure & risk constants, deadline hours, penalty/tier/fee constants, pagination defaults); `types.py` 126 (`Role` enum 7 roles + 30 entity enum tuples); `api_errors.py` 148 (all 57 error ids, HTTP status map via `set_error_http_status_map`, `NOT_FOUND_ERRORS` in PRD order); `test_users.py` 85 (two holders per role, retailer-rep header builder); `api_client.py` 558 (`ApiClient(GenericApiClient)`, one method per declared endpoint — 63 verbs); `factories.py` 248 (21 payload builders); `assertions.py` 173 (17 domain assertions — ledger/reserve conservation, decimal equality, envelopes, version advance); `fixtures.py` 811 (tier-1 wrappers plus 14 `*_env` composites over the canonical docket chain); `__init__.py` 187 (barrel).

**`test_suite/` — conftest + 19 files, 9876 lines, 204 tests.** Queue A (`test_01`–`test_09`): 45 tests. Queue B (`test_10`–`test_19`): 159 tests. Largest: `test_14_validations_fiscal_and_temporal.py` 1213, `test_12_calculations.py` 1208, `test_10_entities.py` 1012, `test_11_state_machines.py` 925, `test_13_validations.py` 814, `test_17_rbac.py` 694, `test_15_endpoints.py` 651, `test_18_cross_cutting_complexity_layers.py` 554.

**Coverage against the design indices:** Queue A — 19 of 20 non-stub difficulty instances, every one with >=2 tests (several with 3). Queue B — 57 of 57 non-stub corner instances across all nine sections; the 8 `excluded_because:` stubs were not translated.

**Instances skipped:** exactly one, on the PRD-first filter — `Difficulty/cross_entity_state_dependency/progress_report_creation_blocked_by_recall_not_yet_monitoring`. It asserts 409 `ERR_RECALL_PLAN_STATE_INVALID` for a progress report opened on an `APPROVED` recall, but PRD §3.8 says a report is opened "against a recall whose `plan_status` is `APPROVED` or `MONITORING`" — the contract contradicts the asserted outcome rather than uniquely deriving it. No placeholder, no xfail; its sibling instance took a third test. One RBAC sub-claim (whether a `RetailerRep` collection read silently filters foreign rows or refuses) was likewise left unasserted because the PRD never states which.

**Verification:** `python3 -m py_compile` clean on all 28 generated modules — nothing truncated. `pyflakes` clean on `test_suite/`. `pytest --collect-only` collects 204 tests with no import errors and no duplicate names. AST audit: 204 tests, 204 `Design:` lines, each exactly one and each the docstring's last line, every tag resolving to a real non-stub instance name; zero dangling, dual, or stub-pointing tags. Nothing written under `workspace/`; no `__pycache__`/`.pyc` left behind.

**Notes carried to Step 7:** eleven sub-generators each hit at least one place where the design index contradicts the PRD, all resolved in the PRD's favour. Recurring ones: the field is `late_surcharge_cents` (not `lateness_surcharge_cents`); a newly registered retailer's `compliance_posture` is `CLEAR`; `channel_type` `INDEPENDENT`/`OUTLET` are not PRD enum members (`SPECIALTY` substituted); PRD §2.8 orders path existence before request shape; the duplicate-evaluation guard covers `REPORTABLE` too; server-owned fields are silently dropped, never a 400. Also corrected mid-run: the canonical chain files its section report two days late (`days_late` 2, `late_surcharge_cents` 500,000, lateness multiplier 1.10), so penalty figures anchor at `assessed_penalty_cents` 5,500,000 for a 4-violation hospitalization docket.

## Step 6: Generate implementation — 2026-09-04T07:20:00.000Z

Implementation complete at `workspace/implementation/` — 2912 lines across 24 files.

**Foundation:** `start.sh` (10) — guarded `pip install` (`if ! python3 -c "import flask"`), `exec python3 app.py`, executable; `requirements.txt` (1); `app.py` (58) — blueprints under `/product-safety` (clock mounted bare), envelope-shaped handlers for `ApiError`/`HTTPException`/unexpected, `app.run(host="0.0.0.0", port=int(os.environ["PORT"] or 10000))`; `store.py` (125) — 13 in-memory dicts, logical clock defaulting to `2026-08-01T00:00:00Z` (never falls back to wall clock), `_seq` insertion counter, helpers; `errors.py` (90) — `ApiError` + all 57 error ids with PRD HTTP statuses; `responses.py` (61) — envelope, `req_` + 20 alnum request id, 3-fractional-digit timestamps, `limit`/`offset`/`total_count`/`has_more`; `auth.py` (49) — `X-User-ID`/`X-User-Role`, 7 roles, unknown role -> 401; `shapes.py` (205) — step-4 shape scope, unknown + server-computed keys ignored silently, pagination bounds 1–100 / >=0; `calc.py` (267) — all 8 calculations, `Decimal` + `ROUND_HALF_UP`, prec 50; `lookups.py` (65) — per-entity not-found errors and the recall->report->evaluation->model chains.

**Routes (`routes/`, 1750 lines):** clock 19, registry 77, incidents 165, patterns 190, evaluations 180, reports 154, recalls 255, notifications 167, visits 117, notices 116, claims 200, progress 167, penalty 174.

**Endpoints:** 63 registered method+path pairs (39 POST, 24 GET) — exact match for the PRD §4 table's 63 rows.

**py_compile:** every `.py` compiled cleanly; `__pycache__` removed afterwards.

**Smoke boot:** `PORT=18675 bash start.sh`, drove a 55-step end-to-end scenario (registry -> intake -> classify -> pattern -> adjudicate -> evaluation -> determine -> report submit/review -> recall -> retailer enrol -> notice -> submit/approve plan -> release -> monitoring -> acknowledge -> audit visit -> verify -> penalty case -> claim approve/fulfil -> progress report -> offer/accept -> close), plus negative probes for 401/403/400/404/409/412/422. All 55 assertions matched expected status; derived figures hand-verified: `risk_index` 27.00, `days_late` 4 / surcharge 1,000,000, `assessed_penalty_cents` 4,500,000, preview 4,050,000 -> 3,825,000 after cooperation bonus -> 2,550,000 consent total with reserve 2,550,000 / available 1,950,000. Server killed by its own listening PID via `ss -ltnp` (no broad `pkill`).

**Notable PRD-over-scaffold fidelity decisions:** §2.8 global ordering authoritative — segregation of duties (step 7) checked before own-state (step 9) on `approve-plan` and progress-report `accept`; `consent_agreement_preview_cents` base = standing offer if any else the assessment, recomputed in exactly three places (open, offer, cascade link 4), not on withdrawal; progress-report accept sets `effectiveness_flag = SHORTFALL` only when `assessment == CRITICAL` (scaffold also said BELOW_TARGET; PRD wins); `effectiveness_flag` flips only `PENDING -> MET` on fulfil; pattern adjudication never touches `hazard_posture`; report review `ACCEPTED` leaves the model untouched (no spurious version bump); `delinquent_count` monotonic, verify sets posture `CLEAR` when `open_stop_sale_count` reaches 0; `created_at`/`updated_at`/`api_request_timestamp` use wall clock, every deadline/window/lateness comparison uses the logical clock; RetailerRep scope (`ERR_RETAILER_SCOPE_VIOLATION`) enforced only on `POST /retailer-notifications/{id}/acknowledge` per the scaffold's `applies_to`.

**Orchestrator note:** Steps 5 and 6 were launched concurrently in a single message, so the impl generator was physically isolated from `test_suite/`. Layout verified afterwards: `test_helpers/` and `test_suite/` at the task root, nothing stray under `workspace/`, single `worklog.md`.


## Step 7: Iterate tests and fixes — 2026-09-04

**Two iterations.** Iteration 1: 196/204 in all eight parallel rounds, the same eight failures
every round (fully deterministic — no flakiness, no reaping). Iteration 2 after the fixes below:
**204/204 in all eight rounds** (~444 s per round under 32-way host contention).

**Failure groups and resolutions.**

1. *Four `created_at`/`updated_at` tests* (`test_10_entities.py`) expected the row stamps to read
   the logical clock; the implementation stamped them from the host wall clock. §4's clock row is
   explicit — "Set the logical UTC clock used by **every timestamp** and deadline comparison in the
   service" — reinforced by §2.4 ("Time in this system is a controllable input rather than an
   ambient fact... it must not fall back to real wall-clock time"). Implementation fix:
   `store.new_row()` and `store.touch()` now call `now_logical()` instead of `wall_now()`.
   `_seq` still drives collection ordering, so a clock moved backwards cannot reorder a page.

2. *One retailer-scope read* (`test_17_rbac.py::test_a_rep_cannot_read_another_retailers_notification`)
   — §2.1 states a retailer representative "may only read the recall, retailer and notification
   records it is party to" and §2.8 step 6 names `ERR_RETAILER_SCOPE_VIOLATION` for "a `RetailerRep`
   acts only on its own notification"; `RetailerRep` *is* on the authorised-role list for
   `GET /retailer-notifications/{id}`, so the refusal must come from step 6, not step 2.
   Implementation fix: `routes/notifications.py::get_notification` now checks
   `actor.user_id == notification["retailer_id"]` for `RetailerRep`, after the step-3 path lookup.

3. *Three progress-report period tests* (`test_14_validations_fiscal_and_temporal.py`) asserted
   byte-exact echo of a client-supplied `period_start`/`period_end` (`"...T00:00:00Z"` vs the
   server's canonical `"...T00:00:00.000Z"`). PRD fixes the rendering of the four common properties
   and `api_request_timestamp` only ("three fractional digits") and asks of a client-supplied
   timestamp merely that it be "a valid ISO 8601 UTC instant" — verbatim echo versus canonical
   re-rendering are both PRD-faithful, so the rendering is not uniquely derivable. Per the partial
   coverage rule the covered claim was kept and the uncovered one dropped: test fix adds a local
   `_assert_same_instant` (the same idiom `test_10`/`test_15` already use for `incident_date` and
   `window_start`) and the three assertions now compare instants. No error-id or status assertion
   was weakened; no test was deleted; no skip or xfail was added.

**Tests deleted:** none. **`test_helpers/` changes:** none — no fixture violated a PRD precondition.

## Step 7: Run tests and iterate (orchestrator record of subagent's returned summary) — 2026-09-04T07:45:00.000Z

Clean sweep achieved.

**Iterations run:** 2

**Final sweep (8 parallel rounds, all completed, observed on disk):** rounds 1–8 each 204/204, 0 failed, 0 errors, 0 skipped (~444 s/round under host contention). All 8 `results.$i.json` left in `workspace/implementation/`.

**Iteration 1** was 196/204 in all 8 rounds with an identical 8-test failure set every round — fully deterministic, no flakiness and no SIGTERM reaping.

**Tests deleted:** none. No PRD-silence casualties; every failing assertion traced to a verbatim PRD sentence, except the one rendering detail handled under partial-coverage below.

**Fixes applied to `test_helpers/`:** none — no fixture, factory, or role-header builder violated a PRD precondition.

**Fixes applied to `test_suite/`** (partial-coverage correction, STEP 1c):
- `test_suite/test_14_validations_fiscal_and_temporal.py` — three tests in `TestProgressReportPeriodSeries` asserted *byte-exact* echo of a client-supplied `period_start`/`period_end` (`"2026-04-12T00:00:00Z"` vs the server's canonical `"2026-04-12T00:00:00.000Z"`). PRD fixes "three fractional digits" only for the four common properties and `api_request_timestamp`; of a client-supplied timestamp §2.8 asks merely that it be "a valid ISO 8601 UTC instant". Verbatim echo and canonical re-rendering are both PRD-faithful, so the rendering is not uniquely derivable. Kept the covered claim (the stored value *is* the supplied instant) via a new local `_assert_same_instant` — the same idiom `test_10`/`test_15` already use for `incident_date`/`window_start` — and dropped the uncovered rendering claim. No error-id or status assertion was weakened; no skip/xfail added.

**Fixes applied to `implementation/`:**
- `workspace/implementation/store.py` — `new_row()` and `touch()` now stamp `created_at`/`updated_at` from `now_logical()` instead of `wall_now()`. PRD §4's clock row: "Set the logical UTC clock used by **every timestamp** and deadline comparison in the service"; §2.4: "it must not fall back to real wall-clock time." (Collection ordering still keys off the insertion counter `_seq`, so a backwards clock move cannot reorder a page.)
- `workspace/implementation/routes/notifications.py::get_notification` — enforces retailer scope for `RetailerRep` (`ERR_RETAILER_SCOPE_VIOLATION`, 403) after the step-3 path lookup. §2.1: a rep "may only read the recall, retailer and notification records it is party to"; §2.8 step 6 names that error, and `RetailerRep` *is* on the authorised-role list for `GET /retailer-notifications/{id}`, so the refusal has to come from step 6 rather than step 2.

**Orchestrator verification (independent of the subagent's claim):** all 8 `results.$i.json` present in `workspace/implementation/`, each complete JSON, each reporting `passed=204 total=204 failed=0 errors=0`.


## Step 8: Finalize PRD — 2026-09-04T07:52:00.000Z

Done. Three edits, all traceable to `<step_7_diff>` items.

**Line counts:** `PRD.md` 440 lines / 101,420 bytes; `PRD_FINALIZED.md` 440 lines / 103,029 bytes. Delta: 0 lines (+0.0%), +1,609 bytes (+1.59%) — three in-place paragraph revisions, no new sections.

**Changes:**
- §2.1 (line 23) — revise — replaced the blanket "may only read the recall, retailer and notification records it is party to" with the impl's actual surface: the ownership check (and `ERR_RETAILER_SCOPE_VIOLATION`) also guards `GET /retailer-notifications/{id}`, and that is the *whole* of scope enforcement — a `RetailerRep`'s recall fetch, retailer fetch and the retailer-notification collection carry no ownership filter — `implementation/routes/notifications.py:27-28`.
- §2.4 (line 84) — insert — pinned that `created_at`/`updated_at` are stamped from the logical UTC clock, never the host wall clock, plus the canonical re-rendering of every resource timestamp (client-supplied instants included) to three fractional digits — `store.py:89`, `store.py:104`, `store.py:52-55`.
- §2.3 (line 78) — insert — clarified that the `created_at`-ascending order (lists *and* cascade sibling ordering) is realised as write order, so a backwards clock move never re-sequences stored rows — `store.py:109-113`, `store.py:90/96`.

**Per-edit pre-edit search log:**

Edit 1 — §2.1 retailer scope. (a) Subject: where `RetailerRep` identity/ownership is enforced, and every endpoint that admits `RetailerRep`. (b) Enumerated: `grep -rn "RETAILER_SCOPE\|RetailerRep" implementation/` -> `routes/notifications.py:27` (GET single, enforced), `:99` (acknowledge, enforced), `:38` `list_notifications` (RetailerRep in `ROLES`, no check), `routes/recalls.py:20/26` `get_recall` (`READ_ROLES` includes RetailerRep, no check; `LIST_ROLES` excludes it), `routes/registry.py:53-57` `get_retailer` (allowed, no check), `auth.py` (roles only), `errors.py:17/77`. No other endpoint admits the role. (c) Adjustment: dropped the PRD's universal read-scope claim instead of merely extending it — an unqualified "may only read records it is party to" would have been a false universal for `GET /recalls/{id}`, `GET /retailers/{id}` and the notification list. Added the explicit "carry no ownership filter at all" clause so Step 9 cannot read scope into them.

Edit 2 — §2.4 timestamp clock + rendering. (a) Subject: which clock stamps row timestamps, and how any timestamp is rendered. (b) Enumerated: `store.new_row`/`store.touch` (only writers of `created_at`/`updated_at`; verified no route assigns either field or `version` directly — only `patterns.py:86` and `penalty.py:106` read `version`); `store.wall_now` callers -> only `responses.py:22` (`api_request_timestamp`); every `store.now_logical()` callsite (13 routes); `store.iso` (single rendering path, used by `serialize` and `routes/clock.py:19`); `shapes.req_ts`/`opt_ts` -> `store.parse_ts` and all 13 body-timestamp callsites (`progress.py:60-61`, `visits.py:55-56`, `patterns.py:78-79/124-125`, `incidents.py:72`, `recalls.py:65`, `notices.py:53/55`, `clock.py:17`) — all store parsed `datetime`, none store a raw string. (c) Adjustment: scoped the clock claim to `created_at`/`updated_at` and scoped the rendering claim to "every timestamp-valued field a resource exposes", deliberately not saying "every timestamp in the service" — `api_request_timestamp` still comes from `wall_now()`, so broader phrasing would have created a new mismatch. Left §4's existing clock-row wording verbatim. Added "any component finer than a millisecond is dropped" because `iso()` floors `microsecond // 1000` while comparisons keep full microsecond precision.

Edit 3 — §2.3 ordering. (a) Subject: the sort key behind collection pages and cascade sibling iteration, now that `created_at` rides a movable clock. (b) Enumerated: `store.ordered` (sorts on `_seq`, the monotonic insertion counter) and every caller — list endpoints in `incidents.py:63`, `patterns.py:47`, `evaluations.py:56`, `reports.py:48`, `recalls.py:53`, `notifications.py:54`, `visits.py:47`, `notices.py:44`, `claims.py:54`, `progress.py:52`, `penalty.py:52` — plus cascade/tie-break uses `recalls.py:100`, `patterns.py:67/110/185`, `evaluations.py:164`, `notices.py:112`, `visits.py:72`, `claims.py:23`, and `calc.py:46-60/85` (`dominant_hazard_code` earliest-created tie-break). All share the one `_seq` key. (c) Adjustment: phrased as "that ordering is realised as the order in which the rows were actually written" and kept the existing `created_at`-ascending sentence intact rather than replacing the sort key outright — the two only diverge after a backwards clock move, which no test exercises, so the looser framing avoids over-pinning while still steering a fresh implementer away from a `created_at` sort.


## Step 9: Complete PRD — 2026-09-04T08:14:00.000Z

Run as **three sequential file-partitioned passes** over `implementation/` (24 files, 2907 lines) rather than one subagent, so the scan could not silently no-op: Pass A = foundation (`app.py`, `store.py`, `errors.py`, `responses.py`, `auth.py`, `shapes.py`, `calc.py`, `lookups.py`, `routes/clock.py`, `routes/registry.py`); Pass B = `routes/{incidents,patterns,evaluations,reports,recalls}.py`; Pass C = `routes/{notifications,visits,notices,claims,progress,penalty}.py`. Pass A created `PRD_COMPLETED.md` from `PRD_FINALIZED.md`; B and C patched the same file with Edit only. Each pass could read the whole implementation for context; only editing authority was partitioned.

**Totals: 29 ambiguity-pins, 4 mismatch-revisions.** Final `PRD_COMPLETED.md` = 440 lines / 108,305 bytes vs `PRD_FINALIZED.md` 440 lines / 103,029 bytes (+5,276 bytes, +5.12%); all edits in-paragraph, no new sections. Orchestrator-verified: file differs from `PRD_FINALIZED.md` (so the scan really ran), all five `## ` headings present, tail ends on `| ERR_EFFECTIVENESS_NOT_MET | 409 |`.

### Pass A (13 ambiguity-pins, 0 mismatches)
No mismatch found: `calc.py`'s eight formulas (severity weight, pattern snapshot, escalation window, lateness, reimbursement, effectiveness rate/assessment, penalty assessment, consent arithmetic) match the PRD's rounding points, floors, caps and boundary strictness exactly; `errors.py`'s `ERROR_STATUS` diffed programmatically against the §5 catalogue — identical both directions; `store.py`'s UUID/`created_at`/`updated_at`/`version` semantics, half-up rounding and write-order `ordered()` match §2.3/§2.4.
- §2.1 — insert — a whitespace-only header counts as empty, and `X-User-Role` is matched exactly (stray whitespace/wrong case -> `ERR_UNAUTHENTICATED`) — `auth.py:32-37`
- §2.2 — insert — `api_request_id` is `req_` plus exactly 20 upper-case-letter/digit characters — `responses.py:21`
- §2.2 — insert — `api_request_timestamp` reads the host wall clock, not the logical clock (`wall_now()` has exactly one call site) — `responses.py:22`
- §2.3 — insert — an empty, non-numeric or fractional `limit`/`offset` is `ERR_INVALID_REQUEST`, not only an out-of-bounds one — `shapes.py:162-179`
- §2.4 — insert — a client instant with no zone designator is read as UTC rather than refused — `store.py:69-70`
- §2.4 — revise — the clock endpoint answers with a `data` object whose single field is `current_utc`, canonically rendered, carrying none of the four common properties — `routes/clock.py:19`
- §2.5 — insert — a body foreign key is shape-checked for presence/non-nullity only; any other present value (non-string included) fails at resolution with the owning entity's not-found error, not `ERR_INVALID_REQUEST` — `lookups.py:26-30`, `shapes.py:41-44`
- §2.5 — insert — enum filters must be declared members; boolean filters accept `true`/`false`/`1`/`0` case-insensitively; identifier filters are opaque and unresolved (unknown id -> empty page) — `shapes.py:183-205`
- §2.8 — insert — shape checks are on the JSON type with no coercion (numeric string / boolean-for-integer are malformed); absent or empty body reads as `{}` so no-required-field actions accept no body, while a non-object or unparseable body is malformed — `shapes.py:27-34, 75-99`
- §3.1 — insert — `model_code` uniqueness is exact string comparison (case and surrounding whitespace significant) — `routes/registry.py:36-38`
- §3.1 — insert — a retailer's `name` carries no uniqueness constraint — `routes/registry.py:60-77`
- §3.5 — insert — `remedy_options` is stored and read back in client-supplied order — `shapes.py:154`
- §4 — insert — trailing slashes are insignificant in path matching; an otherwise unrouted path/method is `ERR_INVALID_REQUEST` (400) with neither header examined — `app.py:26, 37-42`

### Pass B (9 ambiguity-pins, 3 mismatch-revisions)
- §4 (GET /incidents row) — revise — mismatch — the row advertised a "reporting channel" filter that does not exist; replaced with the filters actually implemented (adds duplicate pointer, hazard code) — `routes/incidents.py:36-63`
- §3.1 — insert — optional `note` capped at 2000 characters — `routes/incidents.py:130`
- §3.1 — insert — an explicitly `null` `duplicate_of_incident_id` counts as absent on both branches (legal with `CLOSED_NO_ACTION`, malformed with `MERGED_DUPLICATE`) — `routes/incidents.py:132-140`
- §3.2 — revise — mismatch — the re-point cascade covers any qualifying incident already pointed at an older pattern and preserves its own `status`, so an `ESCALATED` row is re-pointed and stays `ESCALATED` (PRD had said only `CLUSTERED`) — `routes/patterns.py:50-60`
- §3.2 — insert — an optional field supplied as explicit `null` counts as omitted — `routes/patterns.py:123-132`
- §3.2 — insert — well-ordering is checked on the merged *effective* window, so a lone `window_start` is compared with the stored `window_end` — `routes/patterns.py:127-130`
- §3.2 — revise — mismatch — only rows still in `CLUSTERED` are released back to `CLASSIFIED`; an `ESCALATED` row keeps its status and pointer — `routes/patterns.py:62-70`
- §3.2 — insert — a recompute touches neither the model's `version` nor any sibling pattern's `pattern_status` — `routes/patterns.py:141-152`
- §3.2 — insert — optional `note` capped at 2000 characters; the dismissal release is scoped to `status == CLUSTERED`, leaving `ESCALATED` incidents (pointer included) alone — `routes/patterns.py:161,181-188`
- §3.3 — insert — `determination_note` is 1–2000 characters — `routes/evaluations.py:132`
- §3.4 — insert — optional `note` capped at 2000 characters; an `ACCEPTED` decision writes nothing to the product model, so its `version`/`updated_at` do not move — `routes/reports.py:117,126-130`
- §3.4 — insert — explicit `null` counts as omitted, and `reviewed_at` is left standing across a revision — `routes/reports.py:140-153`
- §3.5 — insert — "last open escalation source" defined as no *other* recall on the same model in a `plan_status` other than `CLOSED`; when one remains, the model is not written at all — `routes/recalls.py:238-253`
- §3.6 — insert — the recall row is rewritten only when `IN_PROGRESS -> DEFICIENT` actually fires, so sweeping an already-`DEFICIENT` recall leaves its `version`/`updated_at` untouched — `routes/recalls.py:211-213`

### Pass C (7 ambiguity-pins, 1 mismatch-revision)
- §4 (audit-visits list row) — revise — mismatch — the row advertised a `retailer` filter `list_visits` does not implement; changed to "filterable by notification, status and verdict", matching the impl and §2.5 — `routes/visits.py:28-47`
- §3.6 — insert — the two body foreign keys resolve recall-then-retailer, so a body naming neither live row reports `ERR_RECALL_NOT_FOUND` (the only endpoint with two body FKs) — `routes/notifications.py:65-66`
- §3.6 — revise — `shelf_units_found` is a count "of at least 0", so a negative value is a shape failure (`ERR_INVALID_REQUEST`) rather than reaching `ERR_SHELF_UNITS_PRESENT` — `routes/visits.py:102`
- §3.7 — insert — an `embargo_until` supplied as explicit `null` counts as omitted and stores null rather than being refused — `routes/notices.py:55-57`
- §3.8 — insert — claim approval places no condition on the recall's `plan_status` (unlike registration and fulfilment, which both name that gate), consulting only the claim's own status and the unit ledger — `routes/claims.py:95-110`
- §3.8 — revise — the optional `reason` on voiding is at most 2000 characters — `routes/claims.py:161`
- §3.8 — insert — neither filing nor acceptance of a progress report consults the recall's `plan_status` (the gate applies only at period opening), so a draft opened under monitoring can be filed and accepted after closure — `routes/progress.py:105-167`
- §3.9 — revise — the optional `note` on offer resolution is at most 2000 characters — `routes/penalty.py:145`

**Deliberately left alone (all three passes agreed):** §4 filter lists that are strict *subsets* of the impl (hazard-patterns, evaluations, section-reports, retailer-notifications' `stop_sale_required`, progress-reports' `effectiveness_basis`, civil-penalty-cases' `cooperation_credit_tier`/`cooperation_bonus_applied`) — incomplete but not contradictory; §2.5 pins the full sets and matches the impl exactly. Every authorized-role column and §3 prose role claim was cross-checked against the impl's role tuples — all match. Verified already-unique and unchanged: the audit-window ±24h half-open conflict formula, the four ordered release gates, the four-link fulfilment credit cascade and its `quantity`-based compensation, `MET`-only-from-`PENDING` and `MET` -> `PENDING`/`SHORTFALL` reverts, the `IN_PROGRESS -> SATISFIED` / `DEFICIENT -> IN_PROGRESS` arrow-implied source states, monotonic `delinquent_count` and round counter, the preview's exactly-three recompute sites (withdrawal deliberately excluded), and the retailer counter cascade on verification.

### Pipeline complete
All nine steps done. `workspace/PRD_COMPLETED.md` written. Final green sweep artifacts (`results.1..8.json`, each 204/204) retained in `workspace/implementation/`.
