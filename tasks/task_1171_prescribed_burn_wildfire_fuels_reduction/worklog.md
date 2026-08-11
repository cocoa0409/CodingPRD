# Worklog — task_1171_prescribed_burn_wildfire_fuels_reduction

## Step 1: Create Task Directory — 2026-08-11T08:39:00.000Z

Pre-assigned output folder `tasks/task_1171_prescribed_burn_wildfire_fuels_reduction` with `workspace/` subdirectory already exists; Step 1 treated as done per orchestrator instruction.

## Step 2: Generate Scaffold — 2026-08-11T10:28:00.000Z

Scaffold generation complete. Final lint verdict (verbatim):

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_1171_prescribed_burn_wildfire_fuels_reduction/SCAFFOLD.yaml` (2638 lines; §1.0–§1.7 only, no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1171_prescribed_burn_wildfire_fuels_reduction/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1297 lines; single top-level key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1171_prescribed_burn_wildfire_fuels_reduction/SCAFFOLD_CORNER_DESIGN.yaml` (1688 lines; single top-level key `scaffold_corner_design`)

## Counts

- **Entities: 20** (BurnAssociation, Landowner, Parcel, BurnBoss, Contractor, BurnPlan [self-referential supersession], BurnPermit, PermitNotification, SmokeApproval, ContingencyPlan, IgnitionPlan, ResourceOrder, CrewAssignment, BurnExecution, WeatherObservation, GoNoGoChecklist, Incident, MonitoringReport, CostShareAgreement, LiabilityClaim)
- **State machines: 13** (cyclic plan revision, permit suspend/reinstate loop, contingency reject/revise loop, parallel response×billing axes on Incident, branching escape/wildfire fork on BurnExecution, conditional-target reinstate on CostShareAgreement)
- **Endpoints: 111** · **Errors: 108** · **Roles: 8** · **OCC concurrency rules: 2** · **Calculations: 15**
- **§1.8 instances: 27** (dual_variant_calc 2, combinatorial_formula 3 [modes a/b/c], non_linear_state_machine 4, transitive_cascade 3 [depths 3/2/3, distinct triggers], priority_pair_validation_conflict 3, boundary_precision_check 3, cross_entity_state_dependency 3, resource_temporal_overlap 3 [buffer / closed-gap / aggregate-capacity semantics], compensating_invariant 3)
- **§1.9 instances: 56** (55 active + 1 excluded-because stub), covering all nine taxonomy sections

## Design highlights (harder-than-expert measures)

- Compliance/audit × temporal-windowing archetype with segregation-of-duties (reviewer must differ from plan author by BurnBoss id) plus four cross-cutting layers (OCC, cascading side effects, version-pinning on scheduling, clock-sweep scheduled actions with the mandated 2026-05-01T00:00:00Z default).
- All formula-derived assertions were executed as code and pinned as literals (e.g., per-line-round-then-sum trap 175614 vs 175613; provisional 87807 → final 77844 with conservation 165651; fund cap 300000 from pre-debit balance 600000; partial-band effectiveness 50 → factor 0.75 with negative-installment clawback of 38317).
- Setup chains replayed against §1.2/§1.4/§1.6; three FK reverse-reachability gaps found by the linter were fixed in §1.5 (added `approved_by_boss_id?` filter, `GET /permits` filtered list, de-FK'd the checklist snapshot field). Zero unbound `${var}` placeholders; zero forbidden concurrency vocabulary; error catalog fully referentially closed.

## Step 3: Copy Shared Files — 2026-08-11T10:29:30.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1171_prescribed_burn_wildfire_fuels_reduction/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-11T10:55:00.000Z

All contracts pass. The PRD is complete.

## Summary

**PRD file**: `/home/ubuntu/github/CodingPRD/tasks/task_1171_prescribed_burn_wildfire_fuels_reduction/workspace/PRD.md`
**Line count**: 453 lines

### Section coverage
- **§1 Introduction** — 2 paragraphs (business context + system scope arc), product-manager voice
- **§2 Global Specifications** — 10 subsections: 2.1 RBAC (7 roles + `Any`, per-role identity semantics translated from `identity:` fields), 2.2 Response Structure (**byte-identical** to the canonical `section-2.2-response-structure.md`, verified programmatically), 2.3 Pagination (`limit` 10/1/100, `offset` 0, `created_at` ascending, 4 meta fields), 2.4 Common Resource Properties (UUID/timestamps/version; explicit `common_fields: false` exceptions for WeatherObservation and GoNoGoChecklist; version-increment default with the four silent-bookkeeping exception classes), 2.5 Logical Clock & Sweeps (default `2026-05-01T00:00:00Z`, all four sweep rules), 2.6 Nested Retrieval (left-to-right, all 19 NOT_FOUND codes), 2.7 Validation Order (all 14 priority tiers in prose), 2.8 OCC (both `concurrency_rules` with `expected_parcel_version`/`expected_burn_plan_version` + `ERR_STALE_VERSION`/412), 2.9 Monetary Precision (integer cents, per-line round-half-up then sum pinned order), 2.10 Fund Ledger (reconciliation invariant, compensating reversal, `FUND_RESTRICTED` below 200,000 cents)
- **§3 Business Logic** — 9 subsections organized chronologically by program lifecycle (registry → plan authoring/revision/supersession → permits/notifications/smoke → safety documents → resourcing → burn day → fireline/escape/wildfire → monitoring/cost-share → liability); all 13 calculation rules rendered as precise prose with constants embedded (no pseudocode, no fuzzy words — verified); all cascades (supersession, plan-cancel, wildfire conversion, permit suspension) and the pinned evaluation orders (fund payout pre-debit balance, per-line rounding) expressed
- **§4 Endpoint Definitions** — 111/111 endpoints, 4-column table (Method, Path, Description, Authorized Role), method/path pairs verified against scaffold
- **§5 Error Code Catalogue** — 109/109 errors, 2-column table, HTTP statuses verified against scaffold

### Hard contract verdicts
```
Field coverage check:
- entities[].fields: 118 required, 118 present, 0 missing
- endpoints[].request_body: 79 required, 79 present, 0 missing
- endpoints[].query_params: 0 required (folded into input lists), 0 missing
Status: PASS   (two passes run; pass 1 found burn_permit_id and phase missing — both repaired)

Rule coverage check:
- validations priority ordering: 14 tiers, expressed as explicit ordered prose in §2.7
- OCC rejections: 2/2 expressed (endpoint + occ field + error id + 412)
- state transitions: 100/100 covered (6 heuristic misses manually confirmed; 2 genuine target-state naming gaps fixed: MOP_UP→CLOSED, SCHEDULED→CANCELLED)
- calculations: 13/13 fully expressed in reconstructible prose
- validation conditions: all 71 precondition error ids present near their workflows
- side effects / applies_to scopes: all expressed
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 758
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional checks passed: all 109 error IDs mentioned in §2/§3 prose; all ~98 enum/state values present verbatim; no pseudocode operators (`==`, `>=`, `ceil(`, etc.); no fuzzy words ("approximately", "roughly", …); §2.2 byte-identical to the canonical source; document ends at §5 with no audit footer. The withheld `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened or referenced.

## Step 5: Generate Unit Tests — 2026-08-11T11:35:00.000Z

Generation complete and fully validated. Summary:

## Files written

**`test_helpers/`** (9 files) — `/home/ubuntu/github/CodingPRD/tasks/task_1171_prescribed_burn_wildfire_fuels_reduction/test_helpers/`
- `types.py` — all 16 entity TypedDicts + status enums; WeatherObservation/GoNoGoChecklist correctly carry only `id`+`created_at`
- `api_client.py` — `ApiClient(GenericApiClient)` with 115 methods covering every PRD §4 endpoint
- `api_errors.py` — all 104 error IDs + HTTP map, registered via `set_error_http_status_map`
- `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (per-instance `make_*_headers` builders for the entity-backed roles), `fixtures.py` (composite chains: `setup_burn_ready_ctx`, `setup_closed_execution_ctx`, `setup_partially_disbursed_ctx`, `setup_thirty_day_accepted_ctx`, `setup_adjudicated_claim_ctx`, etc.), `__init__.py` barrel

**`test_suite/`** (9 files) — `/home/ubuntu/github/CodingPRD/tasks/task_1171_prescribed_burn_wildfire_fuels_reduction/test_suite/`
`conftest.py` + 8 numbered test files organized by concern (envelope/registry, plan review cycle, permits/safety docs, crews, execution gates/weather, incidents/wildfire, cost-share fiscal, liability fund).

## Test counts
- **Queue A (Difficulty): 52 tests**, 26 of 27 instances at exactly 2 tests each
- **Queue B (Corner): 55 tests**, 54 of 55 non-stub instances (53 at 1 test, `version_pin_blocks_brief_after_plan_mutation` at 2). The one stub (`cross_cutting_layers/cascading_side_effects_end_to_end`) was not translated; its `difficulty_instance` pointer (`wildfire_declaration_full_chain`) resolves.
- **Total: 107 tests**, all collected by pytest with zero errors.

## Skipped instances (PRD-first filter)
1. **`Difficulty/priority_pair_validation_conflict/permit_issue_safety_beats_notification_constraint`** — the instance asserts ERR_CONTINGENCY_NOT_ACCEPTED beats ERR_NOTIFICATIONS_INCOMPLETE at permit issue, but PRD §2.7's 14-layer taxonomy assigns the notifications-completeness gate to no named layer; two PRD-only readers could order it differently (validation-priority silence).
2. **`Corner/entities/parcel_create_rejects_invalid_enum`** — `ERR_INVALID_ENUM` appears in PRD prose only inside the burn-plan creation sentence (§3.2); §5 defers triggers to narratives, and no narrative names the error for `POST /parcels` (coverage fails).

Deliberate unique-derivability adjustments (not weakenings): version assertions are relative (+1 per mutation) because PRD §2.4 pins increments but not the origin value; contractor window/capacity rejections fire at assignment creation, the endpoint PRD §3.5 pins; the open-claims reinstate test reinstates the permit first so the claims gate is the sole failure.

## Validation verdicts
- `py_compile` clean; all modules import cleanly; `pytest --collect-only`: **107 collected, 0 errors**
- Tag audit: every test has exactly one `Design:` line resolving to a real instance; no untagged/dual-tagged/stub-pointing tests
- Citation audit: 146 quoted PRD citations, **all verbatim** (whitespace-normalized literal substring match against PRD.md)
- No `skip`/`skipif`/`xfail` markers; no scaffold references in generated code; tests import only from `test_helpers` + `pytest`

## Step 6: Generate Implementation — 2026-08-11T11:35:00.000Z

Implementation complete. Final summary:

## Files written

All under `/home/ubuntu/github/CodingPRD/tasks/task_1171_prescribed_burn_wildfire_fuels_reduction/workspace/implementation/`:

- `start.sh` — foreground launcher; guarded dependency install (`import flask` check before `pip install`), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — flask>=3.0,<4.0
- `app.py` — Flask entry, ApiError/404/405/500 handlers in the scaffold envelope, blueprint registration
- `core.py` — in-memory store (empty at boot, no seeding), logical clock (default exactly `2026-05-01T00:00:00Z`, never wall-clock), response envelope (`meta.api_request_id` `req_*`, `api_request_timestamp` ISO-8601 with 3 fractional digits, `response_type`, `data`), `Validator` implementing PRD §2.7 (malformed body pre-auth; field-level checks deferred to last), pagination (`limit` 1–100 default 10, `offset` default 0, `total_count`, `has_more` in `meta`)
- `domain.py` — resource-specific 404 lookups, all calculations (hazard_score, certification_gate, required_holding_force with ceil/floor pins, order fill evaluation, contractor availability with 1-day-buffer window rule, weather prescription check, 60-min freshness, 48h lead time, airshed capacity, provisional/final cost-share with per-line `ROUND_HALF_UP` via `Decimal`, effectiveness score, suppression allocation standard/negligence, fund payout with pre-debit-balance cap), all cascades (supersession, cancel, wildfire→permit→agreements, permit-suspend→agreements), and the four clock sweeps (plan/permit EXPIRED, execution LAPSED, report OVERDUE version-silent)
- `routes_registry.py`, `routes_plans.py`, `routes_permits.py`, `routes_safety.py`, `routes_orders.py`, `routes_exec.py`, `routes_money.py` — endpoint implementations

## Endpoint count

111 spec routes registered (verified by route-table lint; the only extra is Flask's built-in `/static` GET). Matches the PRD §4 table exactly.

## State machines implemented

13: BurnPlan (incl. revision loop, supersession + cancel cascades, EXPIRED sweep), BurnPermit (incl. reinstate/revoke, cascade suspensions), SmokeApproval (incl. conditional→clear, supersede-on-refile, airshed capacity), ContingencyPlan, IgnitionPlan (supersede + plan version bump), ResourceOrder (version-silent fill moves), CrewAssignment (confirm/decline/release/no-show/complete), BurnExecution (13-phase burn-day chain incl. escape fork and LAPSED sweep), PermitNotification, Incident (independent response + billing axes), MonitoringReport, CostShareAgreement (provisional/final disburse incl. negative clawback), LiabilityClaim (pay/reverse/close with compensating fund ledger).

## Self-check results

- **Boot test**: `bash start.sh` from `./implementation/` boots in ~2.5s on `0.0.0.0:$PORT`; verified on default port 10000 and a custom port; repeated fresh-process reboots work (each scenario test ran on a fresh boot).
- **Route lint**: 111/111 expected routes present.
- **Functional smoke (4 scenarios, all ALL PASS)**: (A) full happy path through close + cost-share worked pins (`175614` provisional, score `93`, final `165651`); (B) escape→wildfire cascade, liability adjudication worked pin (landowner 1000000/association 2000000), payout cap pin (300000 from B=600000), reverse/repay ledger restoration, landowner 30-day suspension, plan-not-expired-after-wildfire; (C) auth/malformed/enum errors, supersession cascade, reinstate blocks, plan+permit EXPIRED sweeps, LAPSED sweep, pagination meta, no-show suspension at 2, availability restoration; (D) ignition supersession version silence, `ERR_STALE_PLAN_VERSION` at brief, inclusive weather bounds, negative-clawback disburse crediting the fund, `ERR_NO_DISBURSEMENT_DUE`, OVERDUE sweep version silence.
- `py_compile` clean on all modules; no seeding code anywhere.

One caveat: the association is modeled as a program singleton (first-created), since no entity carries an association FK; under per-test-server isolation each test builds its own fresh world, so this is consistent with the harness.

## Step 7: Run Tests and Iterate — 2026-08-11T11:45:00.000Z

Summary:

- **Iterations run**: 2 full 8-round parallel sweeps (16 runs total).

- **Tests deleted**: none.

- **Fixes applied to `test_helpers/`**: none.

- **Fixes applied to `test_suite/`**:
  - `/home/ubuntu/github/CodingPRD/tasks/task_1171_prescribed_burn_wildfire_fuels_reduction/test_suite/test_07_cost_share_fiscal.py` — `TestPerLineRoundingOrder::test_cost_share_per_line_rounding_priority_tier`: corrected a miscalculated expected literal. The test asserted `provisional_estimate_cents == 202609` with a comment claiming `round_half_up(12*15327*0.75)=137921`; the PRD §3.8/§2.9 per-line round-half-up-then-sum rule yields 12×15327×0.75 = 137943.0 → 137943, plus 3×28750×0.75 = 64687.5 → 64688, summing to **202631**. The implementation already computed 202631 (PRD-correct); the generator had slipped on the intermediate (137921 vs 137943). Fixed the expected value and the comment to 202631/137943. Assertion strength unchanged — the sibling LEGACY test (175614 vs the sum-then-round 175613) remains the discriminating pin for the §2.9 rounding order.

- **Fixes applied to `implementation/`**: none — the implementation was PRD-faithful on every checked rule.

- **Verification**: after the fix, all 8 concurrent rounds report `passed=107 total=107 failed=0`. Before the fix, the same single test failed deterministically in all 8 rounds (`assert 202631 == 202609`), confirming a deterministic test bug rather than flakiness. All other hand-computed literals in the fiscal tests (175614, 87807, 165651, 114953, 38317, 306540, allocation splits, hazard scores) were independently re-derived from PRD prose and verified consistent.

## Step 8: Finalize PRD — 2026-08-11T11:50:00.000Z

Verification complete. PRD_FINALIZED.md is a byte-identical copy of PRD.md — zero edits were warranted.

**Verification of the single Step 7 item** (test-arithmetic bug in `test_07_cost_share_fiscal.py::test_cost_share_per_line_rounding_priority_tier`):

- **PRD already uniquely determines the behavior.** PRD §3.8 (`workspace/PRD.md:203`) pins: per treatment line, `acres` × per-acre rate (15,327 GRASS / 28,750 BRUSH / 46,000 TIMBER) × tier share (0.50 STANDARD / 0.75 PRIORITY / 0.65 LEGACY), "with each line rounded half-up to a whole cent first and the rounded lines then summed (§2.9)". PRD §2.9 (line 115) pins the rounding order and explicitly forbids sum-then-round. For the test's fixture (PRIORITY, 12 GRASS + 3 BRUSH acres): 12×15327×0.75 = 137943.0 → 137943; 3×28750×0.75 = 64687.5 → 64688; sum = 202631. The corrected test literal matches the PRD computation exactly.
- **Implementation is PRD-faithful.** `implementation/domain.py:408-414` (`provisional_estimate`) computes exactly per-line `round_half_up_cents(Decimal(acres) * Decimal(RATE_CENTS[rate_class]) * share)` then sums; constants at `domain.py:18-19` match the PRD values verbatim. The related `final_reimbursement` (`domain.py:437-456`) uses the same per-line-round-then-sum pattern with the effectiveness factor, also PRD-consistent. No PRD silence or mismatch exists anywhere on this subject.

**Summary on exit:**

- **PRD.md vs PRD_FINALIZED.md:** 453 lines vs 453 lines, 0.0% delta — byte-identical (`diff -q` clean). The copy was made per step 0; no edits followed.
- **Changes:** none.
- **Per-edit pre-edit search log:** no edits were committed, so no per-edit log exists. For completeness, the verification search behind the no-edit decision:
  - (a) Subject considered: cost-share `provisional_estimate_cents` per-line round-half-up-then-sum computation (the subject of the single Step 7 test fix).
  - (b) Impl paths enumerated and read: `domain.py:18-19` (RATE_CENTS/SHARE_PCT constants), `domain.py:40-41` (`round_half_up_cents` via `Decimal.quantize(ROUND_HALF_UP)`), `domain.py:408-414` (`provisional_estimate` — the Step 7 site), `domain.py:417-434` (`effectiveness_score`/`effectiveness_factor` — same rounding helper, feeding final reimbursement), `domain.py:437-456` (`final_reimbursement` — parallel per-line rounding consumer), `routes_money.py:397` (installment rounding), plus PRD lines 115, 203, 207 and the full fixed test file. All enumerated paths agree with PRD §2.9/§3.8 as written.
  - (c) Wording adjustment: none — since the PRD already pins every enumerated path's behavior, any added wording could only risk a new mismatch, so none was made.

## Step 9: Complete PRD — 2026-08-11T12:20:00.000Z

All edits applied and verified. The diff is clean: 26 paragraph-level replacements, all inline, no new sections.

## Summary

**Files**
- Source: `workspace/PRD_FINALIZED.md` — 453 lines, 66,265 chars
- Output: `workspace/PRD_COMPLETED.md` — 453 lines, 70,507 chars (+4,242 chars; line count unchanged, all changes are in-paragraph)

**Counts**
- Ambiguity-pins: 29
- Mismatch-revisions: 1

**Changes** (impl paths are under `.../workspace/implementation/`)

- §2.3 — insert — ambiguity — `limit`/`offset` must be integers (else `ERR_INVALID_REQUEST`); out-of-range values clamped (`limit`→[1,100], `offset`→≥0); `has_more` = offset+returned < total_count — core.py:321-342
- §2.3 — revise — ambiguity — default `created_at` ascending sort, ties broken by creation order — core.py:345-348
- §2.4 — revise — ambiguity — `version` starts at 1 on creation; `updated_at` equals `created_at` at creation — core.py:360-367
- §2.4 — insert — ambiguity — version-silent list extended with counter accumulation: contractor `no_show_count` increment and landowner `outstanding_liability_cents` accumulation — routes_orders.py:282, routes_money.py:601
- §2.6 — insert — ambiguity — body-carried identifiers (`landowner_id`, `parcel_id`, `supersedes_plan_id`, `burn_plan_id`, `contractor_id`) reject with the matching resource-specific 404 — routes_registry.py:186-188, routes_plans.py:109-116, routes_orders.py:117-119, routes_money.py:200-205
- §2.10 — insert — ambiguity — all fund movements, posture, airshed-capacity checks, and payout ceilings bind to the first-created association — domain.py:128-132
- §3.1 — revise — ambiguity — fund deposit requires a positive `amount_cents` (else `ERR_INVALID_REQUEST`) — routes_registry.py:119-120
- §3.1 — insert — ambiguity — parcel field-error mapping: shape/`drought_index` range → `ERR_INVALID_REQUEST`, enums → `ERR_INVALID_ENUM`, non-positive `acreage` → `ERR_INVALID_PRESCRIPTION_PARAMS` — routes_registry.py:207-227
- §3.2 — insert — ambiguity — plan drafting requires `X-User-ID` to be a registered burn boss, else `ERR_BOSS_NOT_FOUND` — routes_plans.py:105-107
- §3.2 — revise — ambiguity — error mapping extended: `supersedes_plan_id` on a different parcel → `ERR_INVALID_REQUEST`; `planned_acres` exceeding parcel `acreage` → `ERR_INVALID_PRESCRIPTION_PARAMS` — routes_plans.py:163-165, 190-191
- §3.3 — insert — ambiguity — "the plan's permit" (issuance gates, cascades, sweeps, briefing, reinstatement) means the most recently created permit — domain.py:250-254
- §3.3 — insert — ambiguity — non-positive or over-plan `requested_acres` → `ERR_INVALID_PRESCRIPTION_PARAMS` — routes_permits.py:283-286
- §3.4 — revise — ambiguity — contingency reject `reason` is optional — routes_safety.py:136-138
- §3.4 — revise — ambiguity — ignition `step_index` must equal the entry's 1-based array position (not merely unique/ascending) — routes_safety.py:215-216
- §3.4 — revise — ambiguity — ignition reject `reason` is optional — routes_safety.py:281-283
- §3.5 — insert — ambiguity — a plan may hold several orders; "the plan's resource order" = most recently created non-`CANCELLED` order — domain.py:242-247
- §3.5 — insert — ambiguity — non-positive `units` or `window_end` not after `window_start` → `ERR_INVALID_PRESCRIPTION_PARAMS` — routes_orders.py:145-150
- §3.6 — insert — ambiguity — terminal execution phases enumerated (`CLOSED`, `STOOD_DOWN`, `CANCELLED`, `LAPSED`, `WILDFIRE_RESPONSE`); `ESCAPED` is non-terminal — domain.py:29
- §3.6 — insert — ambiguity — recording weather against a terminal execution → `ERR_INVALID_REQUEST` — routes_exec.py:222-227
- §3.6 — insert — ambiguity — freshness/in-prescription/holding-force preconditions evaluated only when all six answers are `PASS` (a `FAIL` short-circuits to a recorded `NO_GO`); a successful go/no-go returns the recorded checklist as response data — routes_exec.py:300-345
- §3.7 — insert — ambiguity — escape declaration returns the updated execution — routes_exec.py:561
- §3.7 — insert — ambiguity — manual incident report against an execution outside the five phases → `ERR_INVALID_REQUEST`; `ESCAPE` type on a manual report → `ERR_INVALID_ENUM` — routes_exec.py:575-583
- §3.7 — insert — ambiguity — wildfire conversion fires its cascade only when the parent execution is `ESCAPED`; otherwise only the incident changes — domain.py:861-870
- §3.7 — insert — ambiguity — assess-costs evaluates the billing-axis precondition before the response-axis one (both failing → `ERR_BILLING_NOT_UNASSESSED`) — routes_exec.py:686-695
- §3.8 — insert — ambiguity — effectiveness-score planned acreage falls back to the plan's own `treatment_lines` when the plan has no live agreement — routes_money.py:131-136
- §3.8 — insert — ambiguity — the "linked agreement" for `final_reimbursement_cents` recompute = latest-created agreement not `DENIED`/`CANCELLED` — routes_money.py:164-168, domain.py:327-336
- §3.8 — revise — ambiguity — mark-deficient `reason` is optional — routes_money.py:179-182
- §3.8 — revise — ambiguity — agreement deny `reason` is optional — routes_money.py:366-368
- §3.8 — revise — **mismatch** — disbursement dispatches on agreement status: `APPROVED`→provisional, `PARTIALLY_DISBURSED`→final, `FULLY_DISBURSED`→`ERR_NO_DISBURSEMENT_DUE`, every other status→`ERR_AGREEMENT_NOT_APPROVED`; the impl never raises `ERR_AGREEMENT_NOT_PARTIALLY_DISBURSED` (the old text pinned it for the final installment) — routes_money.py:381-385
- §3.9 — insert — ambiguity — a negative `association_share_cents` (negligence share above total cost) clamps the payout to zero and pays zero legitimately — routes_money.py:629-631

No new sections were added; every change is an inline insert or revision of an existing paragraph. Everything else in the implementation (endpoint table, role assignments, state machines, cascades, sweeps, rounding order, formulas, OCC contract, validation precedence per §2.7) was verified to already match the PRD uniquely.
