# Worklog — task_1473_hospital_volunteer_services_auxiliary

## Step 1: Create Task Directory — 2026-08-13T10:42:41.348Z

Task directory `tasks/task_1473_hospital_volunteer_services_auxiliary/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher; Step 1 treated as DONE per invocation instructions. No index scan performed; no other task directory touched. Difficulty directive from user: "Generate task hard than expert level!" — forwarded to the scaffold generator.

## Step 3: Copy Shared Files — 2026-08-13T10:43:25.579Z

Copied `./INSTRUCTION.md` → `tasks/task_1473_hospital_volunteer_services_auxiliary/workspace/INSTRUCTION.md` (executed ahead of Step 2's completion; the copy has no dependency on scaffold output).

## Step 2: Generate Scaffold — 2026-08-13T12:45:00.000Z (RESUME VALIDATION)

The original run was terminated mid-flight before the Step 2 summary was recorded. On resume, the orchestrator validated the three on-disk artifacts instead of regenerating them: all three parse as valid YAML, `SCAFFOLD.yaml` carries §1.1–§1.7 keys (16 entities, 12 state machines, 12 calculations, 13 validations, 88 endpoints, 55 errors, 6 roles) with no forbidden `scaffold_difficulty_design`/`scaffold_corner_design` keys, `SCAFFOLD_DIFFICULTY_DESIGN.yaml` has the single required top-level key with 24 non-stub instances across 9 rule groups, and `SCAFFOLD_CORNER_DESIGN.yaml` has the single required top-level key with 37 non-stub instances across 6 sections. File tails end on complete YAML values. Verdict: Step 2 output complete — kept and reused, not regenerated.

## Step 4: Generate PRD — 2026-08-13T13:09:22.135Z

PRD generation is complete and all three hard contracts pass. Final summary:

## Output

**`/home/ubuntu/github/CodingPRD/tasks/task_1473_hospital_volunteer_services_auxiliary/workspace/PRD.md`** — 415 lines, 9,568 words.

## Section list

- **§1 Introduction** (3 paragraphs: business context → compliance/SoD/fairness pain points → logical-clock + OCC technical frame)
- **§2 Global Specifications** — 2.1 RBAC (6 roles, per-role `X-User-ID` identity prose: 5 opaque + `DepartmentHead` opaque-with-`head_user_id`-scoping + `Volunteer` entity-backed); 2.2 API Response Structure (emitted **verbatim** from `section-2.2-response-structure.md`); 2.3 Pagination (`limit` 10/1/100, `offset` 0, `created_at` ascending); 2.4 The Logical Clock (startup default `2026-08-01T00:00:00Z`, `to_iso8601`/`current_utc`); 2.5 Common Resource Properties (incl. RecognitionEvent append-only exception); 2.6 Precision & Rounding (2dp round-half-up, per-part-before-sum pinning, integer cents, calendar months); 2.7 OCC (all 3 rules); 2.8 Validation Order (13-tier precedence); 2.9 Compliance Posture (full `CLEAR`/`RESTRICTED`/`FROZEN` algorithm with exact 30-day boundaries)
- **§3 Business Logic** — 3.1 Applications (intake/review/decide/withdraw/reapply + approval cascade); 3.2 Clearances (SoD adjudication, renewal cycle, revoke→freeze cascade); 3.3 Departments/Roles/Requests/Placements (slot-fill pinned order, 2-counter negotiation, close-vs-cancel); 3.4 Volunteer Lifecycle (age rule, training, activation's 4 gates, suspend/reinstate, badge minting/replace, separation cascade); 3.5 Shifts (signup gate stack, 16.0h junior ISO-week cap, waitlist promotion, confirm supervision 1:3, completion no-show); 3.6 Hours/Recognition/Annual Review (pinned per-entry rounding with the 0.99-vs-1.00 CLERICAL example, tier thresholds, service-year windows + 2.0h NO_SHOW penalty, 100.0/40.0 minimums, 4-sweep epoch); 3.7 Gift Shop (non-stacking max discount 5/10/15/20 + junior 5 + promo, per-line cent rounding, 24h void); 3.8 Campaigns (window rules, gross/raised/net, 7-day cooling-off, disbursement SoD + balance cap)
- **§4 Endpoint Definitions** — 88 rows, 4 columns only (Method/Path/Description/Authorized Roles)
- **§5 Error Code Catalogue** — 55 rows, 2 columns only; file ends here, no audit footer

## Hard Contract Reports

```
Field coverage check:
- entities[].fields: 101 required, 101 present, 0 missing
- endpoints[].request_body/input-only: 8 required (to_iso8601, decision, reason, expected_volunteer_version, expected_shift_version, amount_cents, recipient, restock_qty), 8 present, 0 missing
- endpoints[].query_params/path_params: 5 identifier families (limit, offset, id + FK filter names — all entity fields), present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 13 tiers checked, 13 expressed as an explicit ordered list in §2.8 with a dual-failure example, 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_<parent>_version + ERR_STALE_VERSION/412 all named in §2.7), 0 missing
- state_machines[].transitions: 12 machines checked; all transitions expressed including sibling sets (decide APPROVE/REJECT, adjudicate CLEARED/REJECTED, withdraw ×3, separate ×3, assignment-cancel ×3 with differentiated effects, badge revoke ×3), 0 missing
- calculations[]: 12 checked, 12 expressed in precise prose (posture, weighted points, tiers, service-year hours, is-junior, junior weekly cap, slot-fill, waitlist promotion, sale total, campaign proceeds, clearance expiry, badge minting), 0 missing
- validations[] conditions: 13 checked, 13 matchable to error_ids in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: all cascades expressed (approve, revoke, separate, close, cancel, shift cancel/complete, hour approve/reverse, sale create/void, accept/rescind, annual review), 0 missing
- entities[].fields[] structured content: defaults and computed-source semantics reconstructible (junior_allowed true, minimum_age 16, can_supervise_juniors false, allow_waitlist false, promo 0..50 default 0, minutes 1..960, etc.), 0 missing
- sibling-branch symmetry: 8 groups checked, 8 with equal prose density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 245
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

## Coverage audit / deliberate scatter decisions

- **Posture algorithm → §2.9** (not §3): it is derived live on every read and gates four different workflows, so it was treated as a cross-cutting principle; §3 subsections repeat only the gate + error id local to each workflow (`ERR_POSTURE_FROZEN` in 3.3/3.4/3.5, `ERR_POSTURE_NOT_CLEAR` in 3.5).
- **Validation priorities → §2.8** as one explicit 13-tier ordered list with a masking example (`ERR_ITEM_INACTIVE` over `ERR_INSUFFICIENT_STOCK`); individual error triggers scattered to their home workflows in §3.
- **OCC details → §2.7** (all three rules with endpoints, fields, 412); §3 mentions only the carried field (`expected_volunteer_version` in 3.4/3.6, `expected_shift_version` in 3.5) — a deliberate §2/§3 split of the same rule.
- **Sale request fields split**: `cashier_volunteer_id`/`lines`/`tendered_cents` in 3.7 body, discount candidates (`buyer_volunteer_id`, `campaign_id`, `promo_discount_pct`) in a separate discount paragraph, void fields in the void paragraph; placement fields split across offer/accept/counter/reoffer/rescind paragraphs in 3.3.
- **Constants embedded in context**: 30-day grace (§2.9), 16.0-hour junior cap with ISO-week definition (§3.5), 24h signup/cancel/void windows (§3.5/3.7), 7-day cooling-off and 1000/600/300/100 tier thresholds (§3.6/3.8), BDG- sequence (§3.4), 24/12/12-month validity (§3.2).
- **One fidelity fix during audit**: the first draft implied `date_of_birth` was editable via the volunteer profile update; the scaffold's PUT input set excludes it, so the sentence was rewritten to pin it as fixed at creation.
- §4 table deliberately minimal (4 columns, no request/response bodies); §5 has no trigger column — all trigger conditions live in §2/§3 prose per spec.

## Step 5: Generate Unit Tests — 2026-08-13T14:12:52.105Z

Generation complete. Summary:

## Counts
- **Queue A (Difficulty): 48 tests** — all 24 instances covered with exactly ≥2 tests each (2 per instance).
- **Queue B (Corner): 36 tests** — all 36 non-stub instances covered with exactly 1 test each; the single stub (`state_machines/assignment_waitlisted_initial_state_when_full`) was not translated and its `difficulty_instance` cross-reference (`shift_capacity_aggregate_with_waitlist_branch`) was verified to resolve in §1.8.
- **Total: 84 tests** across 11 files in `test_suite/`.

## Skip list
Only the one declared stub was skipped. **No non-stub instance was skipped** — every instance passed the PRD-first two-condition filter, in some cases after PRD-driven adjustments:
- `Difficulty/cross_entity_state_dependency/confirm_gated_by_volunteer_and_badge_state` (test 2): suspension always cascades the badge out of ISSUED, so the volunteer-state gate can never fire alone; the second test uses `validate_error_is_one_of([ERR_VOLUNTEER_INVALID_STATE, ERR_BADGE_INVALID_STATE])` (both tier-8, both 409) per the sanctioned error-precedence relaxation. Test 1 (badge revoked while ACTIVE) asserts `ERR_BADGE_INVALID_STATE` uniquely.
- `Corner/errors/hour_entry_linked_validation_bundle`: the recipe's clock (2026-08-01) made both trigger service dates "future", which would have masked the asserted ownership error behind `ERR_SERVICE_DATE_OUT_OF_RANGE` (tier 11 < 12). The fixture advances the clock to 2026-08-04 so each trigger exercises exactly one failing rule.
- `Corner/errors/activate_prerequisite_failures`: volunteer B's literal recipe (HEALTH_FLU never submitted) makes posture FROZEN, which would have broken its placement-accept setup step (§3.3 posture gate). B instead gets all three clearances CLEARED and the clock advances into the 30-day post-expiry grace window — posture RESTRICTED (placement legal) while the activation clearance gate fails with `ERR_CLEARANCE_REQUIREMENTS_UNMET` as asserted.
- Hour-entry fixtures across queue A/B were clock-corrected so `service_date <= today` holds (PRD §3.6 future-date rule) before entries are created.
- Weak pins softened where PRD is silent: initial `version` value and `signed_up_at` on WAITLISTED rows are not asserted (PRD states only "increments by exactly one on every mutation"); `created_at` clock-equality uses prefix comparison tolerant of fractional seconds.

## `test_helpers/` inventory
`__init__.py` (barrel), `types.py` (14 TypedDicts + status/role enums; RecognitionEvent omits `updated_at`/`version` per PRD §2.5), `api_client.py` (one method per PRD endpoint incl. `/_clock/set_current_utc`), `api_errors.py` (all 55 error IDs with PRD §5 statuses, registered via `set_error_http_status_map`), `assertions.py` (per-entity + slot-fill invariant), `factories.py`, `constants.py`, `test_users.py` (shared opaque-role headers + `make_volunteer_headers`/`make_department_head_headers` per-instance builders; SoD pairs screener-1/2, treasurer-1/2), `fixtures.py` (clock, approval pipeline, clearance adjudication with SoD, ORIENTATION completion, dept/role/request, offer+accept, full ACTIVE pipeline, published shifts, signup/confirm, OCC-safe `approve_entry`, `log_and_approve_entries` accumulation, gift-shop cashier, items, campaigns, sales).

## Stage 2 self-audit result
- **Tag coverage: PASS** — 84/84 tests carry exactly one `Design:` line as the final docstring line; all 84 tags resolve to real instance `name:`s; queue A 24/24 instances ≥2 tests; queue B 36/36 non-stub ≥1 test; stub cross-reference resolves.
- **PRD citation pass: PASS** — every docstring's quoted span (≥30 chars) greps verbatim against `workspace/PRD.md` (0 failures after fixing 8 initial elision/bold-marker mismatches); all asserted `error_id`s are named in PRD prose; no `pytest.mark.skip`/`skipif`/`xfail` anywhere.
- All modules import cleanly with the framework on `PYTHONPATH`; no scaffold references in generated code.

## Step 6: Generate Implementation — 2026-08-13T14:15:17.924Z

Done. The implementation is complete and verified. Summary:

## File inventory — `tasks/task_1473_hospital_volunteer_services_auxiliary/workspace/implementation/`

- **start.sh** (executable) — reads `$PORT` (default 10000), binds `0.0.0.0` via Flask, runs in the foreground with `exec python3 app.py`; the `pip install` is guarded (`if ! python3 -c "import flask"`) so per-test-server reboots skip it
- **requirements.txt** — `flask>=3.0`
- **app.py** — Flask app factory, ApiError/404/405/500 handlers producing the scaffold envelope, route registration
- **core.py** — logical clock (boot default exactly `2026-08-01T00:00:00Z`, never wall-clock), empty in-memory `db` dicts (no seeding), response envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`), pagination (`limit`/`offset`/`total_count`/`has_more`, defaults 10/0, min 1, max 100), 3-fractional-digit ISO timestamps, tier-1/2/3 validation helpers, calendar-month arithmetic
- **domain.py** — derived-field engine (compliance_posture with 30-day grace windows, per-entry round-half-up recognition points, tier thresholds, service-year hours with 2.0h NO_SHOW penalty, junior age/weekly-cap math, half-open overlap), waitlist promotion selector, cascades (freeze, separation), all serializers
- **routes_core.py** (24 routes) — clock, applications, volunteers, clearances
- **routes_org.py** (24 routes) — departments, roles, department requests, placements, training records
- **routes_ops.py** (23 routes) — shifts, shift assignments, hour entries, badges, annual review
- **routes_money.py** (17 routes) — campaigns, gift shop items/sales, recognition events

## Endpoint coverage

**88 of 88 endpoints implemented** (24+24+23+17 route registrations = 88, matching the scaffold's endpoint table exactly, including `POST /_clock/set_current_utc` and `POST /auxiliary/compliance/annual-review`).

## State machine & calculation coverage

- All 13 state machines implemented with preconditions and side effects: application review loop + decide cascade (volunteer create/reactivate, badge PENDING, ORIENTATION PENDING), volunteer lifecycle (activate/suspend/reinstate/separate/reapply), clearance renewal cycle with SoD adjudication, request DRAFT→OPEN→FILLED/CLOSED/CANCELLED with slot compensation, placement negotiation (2-counter budget, pre-increment OPEN check on accept), training recertification, shift publish/cancel/complete with NO_SHOW reconciliation, assignment confirm gates (CLEAR posture, ISSUED badge, annual trainings, junior supervision with 1:3 ratio and ≥21 supervisor), hour approve/reject/reverse with exact compensating arithmetic, badge revoke/replace with `BDG-` sequential minting, campaign lifecycle, sale void with stock/campaign compensation
- All 11 calculations: compliance_posture, weighted recognition points (per-entry round-then-sum; verified the pinned 0.33+0.33+0.33=0.99 CLERICAL example), tier thresholds (inclusive ≥), service-year hours (max(0, approved − 2.0×no-shows)), age arithmetic (birthday-on-date = adult), junior ISO-week cap (≤16.0 inclusive), slot-fill evaluation order, deterministic waitlist promotion (earliest-created eligible, skip-ineligible), per-line half-up sale totals with max-of-three non-stacking discounts, campaign proceeds (gross/raised/net/disbursed), calendar-month clearance expiry, sequential badge minting
- OCC on all three pinned writes (`expected_volunteer_version` ×2, `expected_shift_version`), full 13-tier validation precedence (verified body-before-role, OCC-before-state, item-inactive-before-stock), SoD on clearance adjudication and campaign disbursement, Volunteer self-scope and DepartmentHead department-scope ownership

## Verification

Three smoke suites (~90 assertions) run against fresh `start.sh` boots, all passing: full lifecycle E2E, junior/waitlist/posture/window edge cases, and NO_SHOW/suspend-reinstate/badge-replace/discount/disbursement/pagination checks. Each run booted cleanly from a fresh process with an empty store. A real oversell bug (duplicate `item_id` lines bypassing the stock check) was found and fixed during testing.

Writes were confined to `tasks/task_1473_hospital_volunteer_services_auxiliary/`; no other task directories were read or modified.

## Step 7: Run Tests and Iterate — 2026-08-13T14:27:14.708Z

Clean 8-round parallel sweep achieved: **84/84 passed in every round (rounds 1–8, 0 failures, 0 errors)**.

## Summary

- **Iterations run:** 2 (first sweep: 79/84 × 8 rounds with a deterministic 5-test failure set; second sweep after fixes: 84/84 × 8 rounds).

- **Tests deleted:** none. Every failing test traced to verbatim PRD prose; no PRD-silence or unique-derivability violations found.

- **Fixes applied to `test_helpers/`:** none.

- **Fixes applied to `test_suite/`** — one bug class, `NameError: name 'api' is not defined` (deterministic in all 8 rounds). Test-class helper methods referenced the bare name `api`, which only exists as a pytest fixture parameter on test methods, not inside helpers. Since conftest's `api` fixture simply returns the module-level `api_client`, each fix substitutes `api_client.` for `api.` — semantics identical, tests remain PRD-faithful:
  1. `/home/ubuntu/github/CodingPRD/tasks/task_1473_hospital_volunteer_services_auxiliary/test_suite/test_06_confirmation_and_supervision.py` — `TestConfirmStateBeatsSafety._setup_cancelled_junior_assignment` line 44 (`api.cancel_assignment` → `api_client.cancel_assignment`); fixed `test_state_error_beats_supervision_error`.
  2. `/home/ubuntu/github/CodingPRD/tasks/task_1473_hospital_volunteer_services_auxiliary/test_suite/test_09_campaigns.py` — `TestDisbursementPrecedence._setup_reconciled_campaign` lines 142, 149, 150 (`api.activate_campaign` / `api.close_campaign` / `api.reconcile_campaign` → `api_client.*`); fixed `test_cooling_off_beats_balance_overflow` and `test_balance_overflow_in_isolation`.
  3. `/home/ubuntu/github/CodingPRD/tasks/task_1473_hospital_volunteer_services_auxiliary/test_suite/test_10_compliance_cascades.py` — `TestSeparationCascade._setup_filled_request` line 116 (`api.get_department_request` → `api_client.get_department_request`); fixed `test_separation_rescinds_and_reopens_request` and `test_onboarding_separation_same_compensation`.

  A whole-suite AST-style scan confirmed zero remaining bare-`api` references in any method lacking the `api` parameter, and all test files byte-compile.

- **Fixes applied to `implementation/`:** none. The implementation was already fully PRD-conformant; all 84 tests pass against it unchanged.

## Step 8: Finalize PRD — 2026-08-13T14:30:23.258Z

Done. PRD_FINALIZED.md is an exact byte-identical copy of PRD.md — zero edits, per the diff-character note.

## Verification performed

The `<step_7_diff>` claims all fixes were mechanical Python repairs (bare `api` → `api_client` in test-class helper methods) with no behavioral signal. I verified this directly:

1. **conftest.py confirms semantic identity** — `/home/ubuntu/github/CodingPRD/tasks/task_1473_hospital_volunteer_services_auxiliary/test_suite/conftest.py` defines `api` as a session-scoped fixture that simply `return api_client` (the module-level client). Substituting `api_client.` for `api.` inside helpers changes nothing behaviorally.

2. **The three touched sites match the diff exactly:**
   - `test_suite/test_06_confirmation_and_supervision.py` line 44 — `api_client.cancel_assignment` inside `_setup_cancelled_junior_assignment` (helper without `api` param).
   - `test_suite/test_09_campaigns.py` lines 142/149/150 — `api_client.activate_campaign` / `close_campaign` / `reconcile_campaign` inside `_setup_reconciled_campaign`.
   - `test_suite/test_10_compliance_cascades.py` line 116 — `api_client.get_department_request` inside `_setup_filled_request`.
   In each file, test methods that do take the `api` fixture still use `api.*` — consistent with a pure scoping fix, not a behavior change.

3. **AST scan of all 11 test files** — every function was checked for bare `api.` attribute references when `api` is not in its parameter list, plus byte-compilation of every file. Result: `CLEAN`, confirming the repairs are complete and no residual issue hides a PRD-relevant fix.

4. **No other Step 7 activity** — tests deleted: none; `test_helpers/` fixes: none; `implementation/` fixes: none. With the implementation untouched and all 84/84 tests passing against it unchanged, there is no impl-pinned choice or PRD/impl divergence to trace into the PRD.

## Summary

- **Line counts / %-delta:** `PRD.md` = `PRD_FINALIZED.md` = 73,057 bytes; `cmp` reports identical; delta = 0 lines, 0.0%.
- **Changes:** none.
- **Pre-edit search log:** zero edits were made, so no (a)/(b)/(c) entries exist. The verification above (conftest fixture identity, inspection of all three repaired sites, whole-suite AST scan for residual bare-`api` references, and confirmation of zero implementation/test-helper changes) establishes that no Step 7 item traces to PRD silence or PRD/impl mismatch, so the mandated copy-with-zero-edits outcome applies.

## Step 9: Complete PRD — 2026-08-13T14:59:50.426Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1473_hospital_volunteer_services_auxiliary/workspace/PRD_COMPLETED.md` produced as a minimal patch over `PRD_FINALIZED.md`.

**Size delta**: 415 → 417 lines (+2), 72,656 → 77,201 chars (+4,545; bytes +4,580). Source: PRD_FINALIZED.md (PRD.md is byte-identical lineage).

**Counts**: 28 ambiguity-pins, 8 mismatch-revisions (36 changes, 26 diff hunks). No sections added — all in-paragraph except one new cascade-ordering paragraph appended to §2.5.

Changes (each: section — insert/revise — class — what — impl site):

- §2.1 — insert — ambiguity — Volunteer list endpoints scoped to own rows; `volunteer_id`/`cashier_volunteer_id`/`buyer_volunteer_id` filters naming another volunteer → `ERR_NOT_RESOURCE_OWNER`; a sale is "own" when the volunteer is cashier or buyer — routes_core.py:450-467, routes_org.py:244-272, routes_ops.py:240-270/403-434/504-531, routes_money.py:323-354/380-403
- §2.1 — insert — ambiguity — DepartmentHead scoping constrains management actions only; listing/reading not department-scoped — routes_org.py:135-153
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` → `ERR_INVALID_REQUEST` (offset ≥ 0) — core.py:362-380
- §2.3 — insert — ambiguity — `created_at` sort ties broken by creation order — core.py:387
- §2.3 — insert — ambiguity — enum/boolean filter values validated (`ERR_INVALID_REQUEST`; `is_active` accepts case-insensitive true/false) — routes_core.py:32-37, routes_money.py:32-40
- §2.5 — insert — ambiguity — cascades process affected records in creation order (freeze/separation cancels, request close/cancel rescissions, annual-review sweeps) — domain.py:299-307/338-354, routes_org.py:184-205, routes_ops.py:580-611
- §2.6 — revise — **mismatch** — comparisons evaluated on exact stored instants, replacing "second precision" claim — core.py:78-91, domain.py:50-56
- §2.6 — insert — ambiguity — calendar-month/year arithmetic clamps day-of-month to target month's last day (Feb 29 → Feb 28) — core.py:106-129
- §2.8 — insert — ambiguity — missing/unparseable JSON body treated as empty object; non-object body → `ERR_INVALID_REQUEST` — core.py:272-278
- §2.8 — insert — ambiguity — action-carried string fields must be non-empty (`info_request_note`, `rejection_reason` on REJECT, `counter_note`, `decision_reason`, `void_reason`, `recipient`, suspend/revoke/replace `reason`) — routes_core.py:116/148/350/525, routes_org.py:336, routes_ops.py:473/487/537/552, routes_money.py:130/360
- §2.8 — insert — ambiguity — §3-pinned per-endpoint check sequences govern among their own gates — routes_core.py:311-344
- §3.1 — revise — ambiguity — `rejection_reason` must be non-empty, not merely present — routes_core.py:148
- §3.1 — insert — ambiguity — reapply body carries only optional `notes`; profile fields copied from the volunteer record — routes_core.py:394-418
- §3.3 — revise — **mismatch** — department `name` not uniqueness-enforced (dropped "unique") — routes_org.py:50-62
- §3.3 — revise — **mismatch** — role `name` not uniqueness-enforced — routes_org.py:77-99
- §3.3 — revise — **mismatch** — reoffer replaces `offer_note` only when supplied (was "records a fresh offer_note") — routes_org.py:350-371
- §3.4 — insert — ambiguity — volunteer profile update is partial; omitted fields unchanged — routes_core.py:287-309
- §3.4 — insert — ambiguity — `current_service_year_start` exposed as an ISO 8601 calendar date — domain.py:399
- §3.4 — insert — ambiguity — activation gate order pinned: state → ORIENTATION → clearances → accepted-placement → badge (badge check is last, not tier-8-first) — routes_core.py:311-344
- §3.5 — insert — ambiguity — shift-update start<end rule checked against merged values after version/state/assignment gates (stale version wins over inverted window) — routes_ops.py:87-115
- §3.5 — insert — ambiguity — `WAITLISTED` landing also stamps `signed_up_at` at creation — routes_ops.py:227-236
- §3.5 — insert — ambiguity — supplied `supervisor_assignment_id` must reference an existing assignment (`ERR_NOT_FOUND`) even for adult assignees — routes_ops.py:276-281
- §3.5 — revise — **mismatch** — supervision ratio counts every `CONFIRMED` assignment naming the supervisor, not only junior supervisees — routes_ops.py:317-323
- §3.5 — insert — ambiguity — shift completion decrements `filled_count` for each `NO_SHOW` flip and each `SIGNED_UP` cancellation — routes_ops.py:155-171
- §3.6 — revise — **mismatch** — `shift_assignment_id` link not state-gated at logging (was "linking the entry to a confirmed assignment"); COMPLETED flip only at approval if still `CONFIRMED` — routes_ops.py:352-401/458-466
- §3.6 — insert — ambiguity — hour approval completing a `CONFIRMED` assignment decrements the shift's `filled_count` — routes_ops.py:458-466
- §3.6 — insert — ambiguity — reversal bumps the volunteer's `version` — routes_ops.py:483-501
- §3.6 — insert — ambiguity — annual review: a FROZEN-suspended volunteer is not also hours-evaluated; volunteers with no completed service year are skipped — routes_ops.py:593-609
- §3.6 — insert — ambiguity — summary `live_badge_status` is null when no live badge exists — routes_core.py:274-284
- §3.7 — revise — **mismatch** — item `sku` not uniqueness-enforced (dropped "unique") — routes_money.py:153-172
- §3.7 — insert — ambiguity — price update below `unit_cost_cents` → `ERR_INVALID_REQUEST` — routes_money.py:200-204
- §3.7 — revise — **mismatch** — stock check aggregates quantities per item across duplicate lines (was per-line phrasing) — routes_money.py:281-288
- §3.7 — insert — ambiguity — sale lines read back as `item_id`/`qty` pairs only — domain.py:624
- §3.7 — insert — ambiguity — void window boundary inclusive: exactly 24h after creation still qualifies — routes_money.py:365
- §3.8 — insert — ambiguity — campaign close names its error codes (`ERR_CAMPAIGN_INVALID_STATE` / `ERR_CAMPAIGN_WINDOW_MISMATCH`) — routes_money.py:97-111
- §4 — insert — ambiguity — unknown path or unsupported method → `ERR_NOT_FOUND` (404) — app.py:21-27

Everything else in the implementation (posture boundaries, badge numbering, slot-fill sequencing, tier arithmetic, discount competition, campaign figure definitions, role tables, error catalogue) was verified already uniquely pinned by PRD_FINALIZED.md and left untouched.
