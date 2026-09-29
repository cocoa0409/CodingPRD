# Worklog — task_2237_direct_consumer_hearing_aid_remote

## Step 1: Create task directory — 2026-09-01T09:39:22.737Z

Created `tasks/task_2237_direct_consumer_hearing_aid_remote/` and `tasks/task_2237_direct_consumer_hearing_aid_remote/workspace/`.

## Step 2a: Generate SCAFFOLD.yaml (§1.0–§1.7) — 2026-09-01T11:19:00.000Z

Note: the first Step 2 subagent (single agent for all three scaffold artifacts) was terminated by an API timeout after ~62 min with zero files written. Step 2 was therefore re-run split into three subagents: 2a = SCAFFOLD.yaml, then 2b = SCAFFOLD_DIFFICULTY_DESIGN.yaml and 2c = SCAFFOLD_CORNER_DESIGN.yaml launched concurrently.

Subagent summary (verbatim):

`/home/ubuntu/github/CodingPRD/tasks/task_2237_direct_consumer_hearing_aid_remote/SCAFFOLD.yaml` is complete (~4,150 lines), parses as valid YAML, and contains exactly the top-level keys `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` — no `scaffold_difficulty_design`, no `scaffold_corner_design`.

Counts (verified by parsing the file, not from memory):

- Entities: 20 — StatePolicy, Patient, ScreeningSession, RedFlagFinding, Provider, ProviderReferral, RemoteFittingSession, DeviceOrder, Device, TrialPeriod, ReturnAuthorization, FitExchange, InventoryPool, RepairOrder, WarrantyClaim, ReimbursementClaim, CarePlanSubscription, FirmwareCampaign, FirmwareRollout, ComplianceOverride
- State machines: 16 entries across 15 entities (DeviceOrder carries two independent dimensions), 104 states / 126 transitions total: Patient 7, ScreeningSession 5, ProviderReferral 7, RemoteFittingSession 6, DeviceOrder.payment_status 7, DeviceOrder.fulfillment_status 8, TrialPeriod 6, ReturnAuthorization 7, FitExchange 6, RepairOrder 9, WarrantyClaim 7, ReimbursementClaim 8, CarePlanSubscription 5, FirmwareCampaign 6, FirmwareRollout 7, ComplianceOverride 3
- Concurrency rules: 4 (OCC on parent `version` only, 412) — stale TrialPeriod on RA creation, stale DeviceOrder on fit-exchange, stale CarePlanSubscription on tier change, stale Device on manual firmware enrollment
- Calculation rules: 16 (incl. 2 dual-variant calcs, pinned per-component rounding, pinned 5-step evaluation order, benefit waterfall, 3 overlap rules with deliberately different interval semantics, 2 deterministic selectors)
- Validation rules: 65 (priority-ordered safety → constraint/temporal → capacity → fiscal, with 4 documented dual-failure conflicts across 4 distinct category pairs)
- Endpoints: 127 (123 business + 4 test-driving: `/_clock/set_current_utc` with the mandatory `2026-08-01T00:00:00Z` default, `/_payments/simulate`, `/_shipments/scan`, `/_firmware/report`)
- Error catalog: 65
- RBAC roles: 9 — Patient (`entity_backed:Patient`), HearingProfessional and LicensedAudiologist (`entity_backed:Provider`), CareOpsAgent, ReimbursementSpecialist, RepairTechnician, FirmwareEngineer, ComplianceOfficer, PlatformAdmin (all opaque)

Consistency checks I ran against the file: every `error_id` used in validations/concurrency exists in the catalog and every catalog entry is referenced elsewhere; every `METHOD /path` referenced in state-machine triggers, calculation triggers and validation `applies_to` is a declared endpoint (5 alias path-param mismatches were found and normalized); every FK declared in §1.1 has a reverse-reachability GET returning `<Child>[]` (added `GET /red-flag-findings` to close the last two gaps); all endpoint/state-machine actor roles exist in §1.7; every list endpoint carries pagination inputs; forbidden concurrency vocabulary scan is clean. The skill's `scaffold_lint.py` could not be run end-to-end because it requires the sibling `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, which the other agent produces.

## Step 3: Copy shared files — 2026-09-01T11:20:52.672Z

Copied `INSTRUCTION.md` → `tasks/task_2237_direct_consumer_hearing_aid_remote/workspace/INSTRUCTION.md`.

## Step 2b: Generate SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8) — 2026-09-01T12:52:00.000Z

Note: this subagent's first attempt was cut off by an API server error before writing any file; it was resumed via message with an instruction to write incrementally, which succeeded.

Subagent summary (verbatim):

Done. `/home/ubuntu/github/CodingPRD/tasks/task_2237_direct_consumer_hearing_aid_remote/SCAFFOLD_DIFFICULTY_DESIGN.yaml` is complete (~2200 lines, single top-level key `scaffold_difficulty_design`).

**Coverage: 9 / 9 §0.5 difficulty rules, 25 instances total** (minimum is 18). No §0.5 rule was un-instantiable.

| rule | n | differentiation |
|---|---|---|
| `dual_variant_calc` | 2 | Patient candidacy (41.5 PROVISIONAL vs 41.3 PROVIDER_ADJUSTED) vs ReturnAuthorization settlement (FLAT_PCT refund 189376 vs PRORATED_DAILY 193601) — different entity domains |
| `combinatorial_formula` | 3 | mode b (per-component rounding before sum, 12378 not 12377), mode c (service-fee waiver on subtotal not discounted, 8910 not 9405), mode a (deductible tier product then integer surcharge, 8713 not 8712) |
| `non_linear_state_machine` | 3 | DeviceOrder parallel dimensions, ProviderReferral reschedule cycle → cap, RepairOrder fork-join REPAIRED vs UNREPAIRABLE |
| `transitive_cascade` | 2 | depth-5 chain from `/return-authorizations/{id}/settle`, depth-4 fan-out from `/screening-sessions/{id}/submit` |
| `priority_pair_validation_conflict` | 3 | referential(13)/safety(28) → 404; temporal(34)/constraint(40) → 409; state(19)/constraint(42) → 412 |
| `boundary_precision_check` | 3 | capacity equality (POST /remote-fitting-sessions), 86399 s → 0 days (POST …/inspect), advisory sum == 2.5 inclusive (POST …/submit) |
| `cross_entity_state_dependency` | 3 | (Session, Order), (Subscription, TrialPeriod), (Rollout, Subscription) |
| `resource_temporal_overlap` | 3 | Provider half-open + buffer + strict (adjacency OK), FirmwareCampaign closed + non-strict (touching collides), TrialPeriod closed pause intervals + inclusive 60-day budget |
| `compensating_invariant` | 3 | cash (210096 == 189376+20720+0 → 210096+0+0), inventory (2/1/0 → 3/0/0 of 3), benefit (60000/25000/65000 → 0/0/150000 of 150000) |

Self-verification run against `SCAFFOLD.yaml` (replicating the Quality Checklist): YAML parses; all 25 instance names unique; **0 problems** across (a) every `call:` resolving to a declared §1.5 endpoint, (b) every `as:` role declared *and* permitted on that endpoint, (c) every payload key ⊆ the endpoint's `input`, (d) every `captures:` field present in the output entity, (e) every `expected_*_version` an expression over a captured var (never a literal), (f) placeholder closure in calls, payloads, `as_user_id` and asserts; no `round(...)` in asserts. All grounds refs resolve (0 bad) against `calculations`, `validations[priority]`, `concurrency_rules[rule_id]`, `state_machines.<Entity>.<FROM>_to_<TO>` and `entities.<E>.fields.<f>`.

Bugs found and fixed during that verification (all in the last two appended chunks, where I had mis-remembered names): `POST /care-plan-subscriptions/{id}/activate` does not exist — plans activate as a side effect of the `DELIVERED` scan, so the enrollment call was moved ahead of the scan; `run-billing-cycle`/`retry-payment` take `charge_outcome` (not `outcome`) and `retry-payment` is Patient-only; `POST /firmware-campaigns` takes `campaign_code`/`model` (not `name`/`target_model`, and the entity field is `model`); `advance-batch` → `advance`; repair transitions are `/start` and `/resolve {resolution}` (not `begin-repair`/`complete-repair`) with `return-to-patient` restricted to RepairTechnician; `Device` has no declared state machine and `ReturnAuthorization` has no REFUND_SETTLED self-loop (the waiver's transition is `DeviceOrder.PARTIALLY_REFUNDED_to_REFUNDED`).

I did not read or write `SCAFFOLD_CORNER_DESIGN.yaml`, and did not open any sibling task directory (I also skipped `scaffold_lint.py` because it would read the corner file; my checks above cover the same six items).

## Step 2c: Generate SCAFFOLD_CORNER_DESIGN.yaml (§1.9) — 2026-09-01T14:26:00.000Z

Subagent summary (verbatim):

The §1.9 artifact is complete and validated.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2237_direct_consumer_hearing_aid_remote/SCAFFOLD_CORNER_DESIGN.yaml` (5,114 lines, single top-level key `scaffold_corner_design`)

**Sections emitted (all nine legal §1.9 sections, no invented ones) and instance counts:**

| section | instances |
|---|---|
| entities | 16 |
| state_machines | 25 |
| calculations | 39 |
| validations | 15 |
| endpoints | 10 |
| errors | 30 |
| rbac | 15 |
| cross_cutting_complexity_layers | 14 |
| consistency_model | 2 |
| **total** | **166** |

**Machine-checked properties** (script run over the parsed YAML): valid YAML with exactly one top-level key; every instance has `name`, `claim_type`, `grounds`, `distinguishing_aspect`, `test_recipe`; every recipe has `setup`, `setup_api_calls`, `trigger`, `assert`; every API call carries `call` + `as`; zero unbound `${...}` placeholders (all resolved by an earlier `captures:`); zero unique-name collisions; zero TODO/TBD/placeholder/`excluded_because` occurrences.

**Coverage highlights**
- All 65 catalog errors are forced somewhere; `errors` holds the residual 30 not already forced elsewhere. Two structural findings recorded explicitly rather than faked: `ERR_UNKNOWN_ROLE` is unreachable (a declared role header is always required), and `ERR_DUNNING_LIMIT_REACHED` is permanently shadowed by priority 22 (the third dunning failure suspends the plan), so that instance pins `ERR_INVALID_STATE` and documents the shadowing.
- `rbac` denies each role's exclusive operations to a peer, plus `ERR_NOT_ASSIGNED_PROVIDER`, `ERR_PROVIDER_TYPE_NOT_PERMITTED` (TELECARE_FITTER behind the LicensedAudiologist header), `ERR_PROVIDER_CONFLICT_OF_INTEREST`, `ERR_NOT_RESOURCE_OWNER`, both segregation-of-duties pairs via `X-User-ID`, and the priority-4-before-priority-10 ordering (403 not 404 on a nonexistent id).
- `cross_cutting_complexity_layers` covers exactly the five declared layers, with one OCC instance per §1.2.1 rule (trial/order/subscription/device, each asserting the 412, the unchanged side state, and the successful replay at the observed version), CASCADE-A end-to-end with `captured == refunded + retained + open` at 215995 = 194500 + 21495 + 0, CASCADE-B ordering-sensitivity and scope-filter, dual-variant divergences (candidacy 39.3 vs 39.4; restocking FLAT_PCT 20000 vs PRORATED_DAILY 5000, delta 15000; WAIVED reconciliation delta 21495), version pinning surviving a later policy PATCH, and both selectors.
- Every recipe pins the logical clock first and uses verbatim endpoint paths, field names, enum literals and pre-computed expected values; no row-order assertions are made on generic lists since SCAFFOLD.yaml declares no default ordering (ordering edges use rank/partition semantics instead).

`SCAFFOLD_DIFFICULTY_DESIGN.yaml` was never read or written, and no sibling task directory was accessed.

## Step 4: Generate PRD — 2026-09-01T11:48:00.000Z

Note: Step 4 was launched as soon as SCAFFOLD.yaml existed, concurrently with Steps 2b/2c (the PRD depends only on SCAFFOLD.yaml, and both design indices are withheld from it by contract).

Subagent summary (verbatim):

PRD written to `/home/ubuntu/github/CodingPRD/tasks/task_2237_direct_consumer_hearing_aid_remote/workspace/PRD.md`.

**Size:** 594 lines. Written in 1 `Write` + 3 small `Edit`s + 1 appended script-generated block (§4/§5 tables emitted directly from `SCAFFOLD.yaml`, so paths, descriptions, roles, error IDs and statuses are transcription-exact).

**Section list**
- §1 Introduction (3 paragraphs + mount-point note)
- §2 Global Specifications & System-Wide Principles — 2.1 User and Role-Based Access Control; 2.2 API Response Structure; 2.3 Pagination; 2.4 Resource Identity, Timestamps and the Logical Clock; 2.5 Nested Path Resolution and Regulatory Version Pinning; 2.6 Money, Precision and the Cash-Conservation Ledger; 2.7 Optimistic Concurrency: Stale-Version Guards; 2.8 Cascades, Derived Fields and Immediate Consistency; 2.9 Request Evaluation Order; 2.10 Segregation of Duties; 2.11 Status Codes
- §3 Business Logic & Workflows — 3.1 Onboarding a Patient Under a State Policy; 3.2 Self-Administered Screening, Red Flags and Candidacy Scoring; 3.3 Referral, Clearance and Dual-Control Overrides; 3.4 Remote Fitting: Capacity, Slot Geometry and Attendance; 3.5 Ordering, Fit Confirmation, Inventory and Shipment; 3.6 The Trial Clock, Returns, Restocking Settlement and Fit Exchanges; 3.7 Repairs, Warranty Claims and Device Replacement; 3.8 Care Plans, Billing Cycles and Reimbursement Paperwork; 3.9 Firmware Campaigns and Rollout Mechanics
- §4 API Endpoint Definitions (4-column table, 127 rows)
- §5 Error Code Catalogue (2-column table, 65 rows) — file ends here, no footer

**Coverage (machine-verified against the scaffold)**
- 20/20 entities; **every** `entities[].fields[].name` appears in backticks (0 misses), including `RedFlagFinding`'s `common_fields: false` status stated explicitly in §2.4
- 16/16 state machines, 78/78 distinct states in backticks, all 126 transitions narrated with preconditions paired to error IDs and side effects; both named cascades documented hop-by-hop (return-settlement hops 1–5, medical-hold hops 1–4)
- 16/16 calculations with constants, inclusive/exclusive boundaries, and normative evaluation/rounding order (per-component rounding in restocking, single-terminal rounding in candidacy, five-step care-plan charge, post-rounding caps)
- 4/4 concurrency rules as OCC stale-version guards with `expected_*_version` field, endpoint, and 412 error IDs
- 65/65 validations enumerated in explicit priority order 1→65 with condition, error ID, HTTP status and `applies_to` endpoints, plus the four documented dual-failure precedence resolutions
- 127/127 endpoints; every `input` identifier and every path parameter appears in backticks (0 misses)
- 65/65 error IDs appear in §1–§3 prose as well as in §5
- 9/9 roles with identity semantics (`entity_backed` vs opaque) and `X-User-ID`/`X-User-Role`

**Hard contracts:** Contract 1 (field-name coverage) PASS — 0 missing entity fields, 0 missing endpoint input/path identifiers. Contract 2 (rule coverage) PASS — priority ordering, OCC framing (no "simultaneously"/"race"/"first-writer-wins" language), cascades, `applies_to` enumeration, defaults/initial values, and sibling-branch symmetry (repair fork A/B, warranty replace/repair, campaign abort from `PAUSED` vs `SCHEDULED`) all present. Contract 3 (§3 path purity) PASS — 0 backticked tokens in §3 begin with `/`, are a bare HTTP method, or combine method+path. §2.2 is byte-identical to `section-2.2-response-structure.md`.

Both withheld design files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced, and no sibling task directory was accessed.

## Step 5: Generate unit tests — 2026-09-01T17:22:00.000Z

Subagent summary (verbatim):

Test suite generation for task_2237 is complete and verified.

## Files created

**Stage 1 — `test_helpers/`** (9 modules, imports clean, 65 error ids registered):
`__init__.py`, `types.py` (9 roles + ~30 status enums + 20 entity TypedDicts), `api_client.py` (`ApiClient` over `GenericApiClient`, `/hearing-care` prefix, one method per endpoint incl. the four test-driving hooks), `api_errors.py` (`ApiErrorId` + `HTTP_STATUS_CODES` registered via `set_error_http_status_map`), `assertions.py` (per-entity assertions, event-row assertion for `RedFlagFinding`, and the three conservation checkers), `factories.py`, `constants.py`, `test_users.py`, `fixtures.py` (5-tier composite setup helpers).

**Stage 2 — `test_suite/`**: `conftest.py` + 19 test modules (`test_01` … `test_20`), ~15.5k lines total.

## Test counts

| | tests | instances covered |
|---|---|---|
| Difficulty (queue A) | 68 | 24 / 25 (9 rules; every covered instance has ≥2 tests) |
| Corner (queue B) | 167 | 164 / 166 (9 sections) |
| **Total** | **235** | |

`PYTHONPATH=. python3 -m pytest test_suite --collect-only -q` → **235 tests collected**, no errors.

## Instances skipped (3, all not-uniquely-derivable — no PRD-silent skips, no stubs/xfail)

1. `Difficulty/cross_entity_state_dependency/subscription_reinstate_blocked_by_settled_return` — the precondition is unreachable through the documented surface: §2.8 hop 4 of the return-settlement cascade cancels every subscription attached to the order, so a `SUSPENDED` plan whose trial is `RETURN_SETTLED` cannot exist.
2. `Corner/state_machines/sm_order_confirm_fit_blocked_when_payment_not_authorized` — §2.9 rule 24 does not list `confirm-fit`, so `ERR_DEPENDENT_STATE_NOT_READY` vs `ERR_INVALID_STATE` is not pinned by PRD text.
3. `Corner/rbac/rbac_provider_conflict_of_interest_on_referral_evaluation_booking` — the setup requires invalidating the `SCORED` triggering session, but §3.2 pins invalidation to an `IN_PROGRESS` origin, so the conflict-of-interest denial is not observably reachable.

## Audits run (both mandatory final passes)

- **Design-index sweep**: every test carries exactly one `Design:` line, last in its docstring; all 235 tags resolve to real instance names character-for-character; zero unknown/dual tags.
- **PRD-citation sweep**: all 492 quoted citations plus the unquoted excerpts verified as verbatim substrings of `workspace/PRD.md`. I repaired 54 citation defects found in the generated files — 22 arrow/em-dash renderings, 21 elisions, and 11 genuine paraphrases (including one hallucinated trial lifecycle `ACTIVE/PAUSED/EXPIRED/CONVERTED…` sentence) replaced with the real PRD sentences.
- One assertion tightened as a consequence: the settled-trial extend test now asserts `ERR_INVALID_STATE` outright (rule 22 < rule 23 under the PRD's explicit "lowest priority number wins"), replacing a `validate_error_is_one_of` hedge.
- No `skip`/`skipif`/`xfail`, no mocking, no server lifecycle code, no scaffold references, and none of the three non-existent error ids anywhere.

## Helper bugs I fixed after subagent reports

`create_provider_payload` npi was 9 digits (PRD requires ten); `create_inventory_pool_payload` sku was `SKU-nnnn` instead of the PRD's model-dome-tip join; `create_fit_exchange_payload` defaulted to invalid dome size `LARGE` → `L`; `create_firmware_campaign_payload` carried a non-PRD `failure_rate_abort_pct` and a window outside the startup clock; `assert_provider` allowed a non-existent `INACTIVE` status (PRD: `ACTIVE`/`SUSPENDED`/`OFFBOARDED`); three `charge_outcome: "SUCCESS"` literals normalized to the canonical `"SUCCEEDED"`.

Caveat: nothing was executed against a live server — verification was collection, import, API-surface and citation level only.

## Step 6: Generate implementation — 2026-09-01T16:26:00.000Z

Subagent summary (verbatim):

All 127 endpoints are implemented and the file set boots cleanly.

## Modules (`workspace/implementation/`, 4,897 lines total)

| file | lines | contents |
|---|---|---|
| `app.py` | 71 | Flask factory, 8 blueprints under `/hearing-care`, ApiError/400/404/405/HTTPException/500 handlers, threaded run on `$PORT` (default 10000) |
| `store.py` | 158 | 20 in-memory dict tables, logical clock pinned to `2026-08-01T00:00:00Z`, record/`bump`/`serialize`/ordering helpers, RMA sequence |
| `errors.py` | 146 | all 65 error ids → HTTP status + default messages |
| `resp.py` | 116 | envelope, `req_`+20-char id, list meta, pagination (`ERR_INVALID_PAGINATION`) |
| `bodyspec.py` | 147 | typed body reader; enum membership deferred to `finish()` so rule 15 precedes rule 16 |
| `auth.py` | 114 | 9 roles, entity-backed Patient/Provider identity, owner / assigned-provider / provider-type / SoD / conflict-of-interest guards |
| `calc.py` | 565 | all 16 calculations + normative constants (Decimal ROUND_HALF_UP, integer cents, 1-dp percentages, floored days) |
| `services.py` | 550 | shared domain layer: state guards, lazy expiry, counter recomputation, CASCADE-A (5 hops) and CASCADE-B (4 hops), plan credit/charge, rollout cancellation |
| `common.py` | 72 | list filtering + Patient owner scoping + pagination |
| `routes_policy.py` | 522 | state policies, patients, screening sessions (submit scores in-request), red-flag findings, compliance overrides — 25 endpoints |
| `routes_provider.py` | 457 | providers, referrals, remote fitting sessions — 18 |
| `routes_order.py` | 273 | device orders (policy version pinning + `_pinned_policy` snapshot), devices, inventory pools — 14 |
| `routes_trial.py` | 399 | trial periods, return authorizations, fit exchanges — 17 |
| `routes_repair.py` | 410 | repair orders (fork/join) and warranty claims — 17 |
| `routes_finance.py` | 449 | care plan subscriptions and reimbursement claims — 16 |
| `routes_firmware.py` | 295 | campaigns, cohort advance, rollouts — 15 |
| `routes_test.py` | 144 | `/_clock/set_current_utc`, `/_payments/simulate`, `/_shipments/scan`, `/_firmware/report` — 4 |
| `start.sh` | 8 | executable launcher, `exec python3 app.py`, honours `$PORT` |

## Verification
- **Route count: 127** registered rules, exactly matching the spec's 127 endpoints (`url_map` introspection).
- **Boot smoke check passed**: server launched via `./start.sh` on free ports, trivial calls returned correct envelopes, then killed. No listeners left behind.
- Three end-to-end functional passes ran green against a fresh process: (1) policy → patient → waiver → screening submit → pool/device → order → payment auth → confirm-fit → ship → deliver (trial created, plan activated) → return authorization → pickup → receive → inspect → settle (CASCADE-A), (2) fitting session start/complete, repair kit→receive (trial paused)→resolve→return-to-patient (turnaround 20 d, SLA credit capped at 5,000), warranty DAMAGE claim triage (deductible 3,713 = 9,900×0.5×0.75 half-up), REPLACE → pay-deductible → fulfill, firmware campaign schedule/advance/offer/install/report SUCCESS, billing cycle (PREMIUM 8,900 → 10,900, fee waived), reimbursement waterfall (eligible 20,000 → insurance 15,000 / FSA 5,000 / patient 0) → pay, (3) fit exchange reserve/ship/confirm with pool movements, trial extend, return void, mid-cycle tier change proration, repair UNREPAIRABLE → escalate (auto DEFECT claim), manual enrollment with OCC on device version, duplicate-subject refusal, plan cancel, and the auth/pagination/404 error paths (400/401/401/403/404).
- Storage is in-memory dicts only — no SQLite, no disk dump, no seeding; every entity in the runs above was created through the API.

Two deliberate spec-conflict resolutions worth flagging: fit-exchange with a depleted pool returns `ERR_INVENTORY_POOL_DEPLETED` when `allow_backorder` is false and creates a `REJECTED`/`POOL_DEPLETED` row when it is true (the only reading consistent with both validation rule 52 and the endpoint's side-effect list); the trial-not-active gate lands as a `REJECTED`/`TRIAL_NOT_ACTIVE` row since no error id exists for it. Unrelated note: other `python3 app.py` processes are being spawned concurrently on this host by the test-generation agent's harness; I left those alone.

## Step 7: Run tests and iterate — 2026-09-01T21:05:00.000Z

Subagent summary (verbatim):

All 8 parallel rounds are green.

## Summary

**Iterations run: 3** (sweep 1: 215/235 in all 8 rounds; sweep 2: 231/235 in all 8; sweep 3: **235/235 in all 8 rounds**, identical results, zero flakiness observed in any round).

### Tests deleted
**None.** Every one of the 20 original failures traced either to a verbatim-PRD-covered implementation bug or to a test fixture that itself violated a PRD precondition. No assertion was weakened, skipped, or xfailed.

### Fixes applied to `test_helpers/`
- `/home/ubuntu/github/CodingPRD/tasks/task_2237_direct_consumer_hearing_aid_remote/test_helpers/assertions.py` — added `parse_instant()` / `assert_same_instant()`. PRD §2.4 mandates "a `created_at` timestamp in ISO 8601 UTC form with **three fractional digits**", so `...T00:00:00.000Z` is the PRD-required form and raw string equality against `...T00:00:00Z` was the test's bug, not the implementation's. (Precedent already existed in-suite: `test_07`'s `_same_instant`, `test_18`'s `_instant`.)

### Fixes applied to `test_suite/` (7 test-side bugs, all PRD-inconsistency)
- `test_04_settlement_and_screening_cascades.py` (`test_red_flag_submit_scores_the_session_and_opens_a_referral`) — `issued_at` / `expires_at` now compared as instants.
- `test_06_threshold_boundaries.py` (two tests) — `started_at`, `expires_at`, `return_deadline_utc` compared as instants.
- `test_16_error_catalogue.py` (`test_repair_decision_is_rejected_after_the_warranty_term_ends`) — `warranty_expires_at` compared as instants.
- `test_05_validation_precedence.py` (`test_rejected_late_return_...`) — `effective_end_utc` compared as instants.
- `test_07_cross_entity_gates.py::_setup_pending_rollout_with_past_due_plan` — the fixture wrapped a DECLINED billing cycle in `get_success_data`. Per §2.9 rule 62 a declined instrument returns 402 `ERR_PAYMENT_DECLINED` *while* §3.8 still commits `ACTIVE → PAST_DUE`; the fixture now asserts 402 and re-reads the plan.
- `test_13_benefits_warranty_and_capacity_math.py:669` — campaign `model="AURA"`; PRD §3.5 declares the model set as `NEO`, `LINK`, `FLEX`. Changed to `LINK` (still a different model, so the "different-model campaign over the identical window" proof is intact).
- `test_18_cross_cutting_layers.py` — (a) `_settle_whole_order_return` and the inline copy at ~line 598 skipped the carrier pickup scan; §3.6 requires `ISSUED → IN_TRANSIT → RECEIVED`, so a `RETURN_PICKED_UP` scan was inserted (`order_id` threaded through the helper's 5 call sites). (b) `PATCH /state-policies/{id}` sent `trial_period_days: 10`, below the §3.1 minimum of 30; changed to 30 (still ≠ the pinned 45, so the non-repinning proof is intact).

### Fixes applied to `implementation/`
- `routes_test.py::set_clock` — removed the eager `touch_all_referrals/trials/return_auths` sweep. PRD §2.4: expired referrals, return authorizations and trials "transition on the next read or write that touches them, **not at the moment the clock advanced**". The eager sweep bumped `TrialPeriod.version` at clock-move time, making §2.9's late-return dual-failure scenario unreachable (it surfaced as `ERR_STALE_TRIAL_VERSION`).
- `routes_trial.py::create_return_auth` — hoisted the `ERR_TRIAL_WINDOW_CLOSED` check above `ensure_state`. PRD §2.9: "a return request made after `effective_end_utc` on an order whose device is currently in repair … rule 34 wins, so the caller sees `ERR_TRIAL_WINDOW_CLOSED`". The window-open + `RETURN_SETTLED` path still yields `ERR_ALREADY_TERMINAL`, preserving `test_14`'s rule-18-before-rule-23 test.
- `routes_trial.py::extend_trial` — same hoist, and dropped the terminal-table argument so a `RETURN_SETTLED` trial reports `ERR_INVALID_STATE` (§2.9 rule 22 governs action endpoints with a declared origin set).
- `routes_trial.py::cancel_fit_exchange` — origin states made role-scoped: §3.6 says cancellation is "available to the patient from `RESERVED` and to a care operator from `SHIPPED`". A patient cancelling a SHIPPED exchange now correctly hits rule 22.
- `routes_finance.py::run_billing_cycle` — dropped the terminal-table argument so a CANCELLED plan reports `ERR_INVALID_STATE`, matching §2.9 verbatim: "A billing-cycle run against a cancelled subscription with a declining instrument violates both rule 22 and rule 62; rule 22 wins".
- `routes_firmware.py::manual_enrollment` — removed an unstated `campaign.status ∈ {SCHEDULED, ROLLING, PAUSED}` gate. PRD §3.9 and §2.9 rules 21/33 name only the device-version guard and the consent predicate for this endpoint; no campaign-state precondition exists.
- `routes_firmware.py::offer_rollout` — split one conflated check into two. §3.9's "either the device's plan to be `ACTIVE` or `TRIALING` or the campaign's `is_mandatory_safety` to be true" is a *sibling-entity* precondition → §2.9 rule 24 `ERR_DEPENDENT_STATE_NOT_READY`; the separate consent flag (`firmware_auto_update_enabled`, which §3.8 defaults to true) is rule 33 `ERR_AUTO_UPDATE_NOT_CONSENTED`, checked second per priority order.

**Note on host conditions:** an earlier sweep attempt died because a concurrent sibling session on this host used identical `/tmp/sweep2_$i.log` paths (its log showed a different task's output). Sweeps were relaunched with `nohup` into a private `/tmp/sweep_2237/` directory, and no `pkill` was used, to avoid interfering with (or being interfered with by) other sessions' servers.

## Step 8: Finalize PRD — 2026-09-01T21:20:00.000Z

Subagent summary (verbatim):

All 8 edits landed on 8 lines; no structural changes.

## Result

`PRD_FINALIZED.md` written. **593 → 593 lines (0.0% line delta); 139,160 → 142,266 bytes (+2.2%).** 8 lines revised, no new sections, no deletions.

### Changes

- **§2.4 (line 88) — insert** — all instant-valued fields (not just `created_at`/`updated_at`) are serialized as `YYYY-MM-DDTHH:MM:SS.mmmZ` with three fractional digits always present; illustrative list of deadlines/window/cycle/pause fields — `implementation/store.py:67-76` (`iso`), `store.py:134-146` (`serialize`), `resp.py:19-24`.
- **§2.9 rule 33 (line 165) — revise** — manual-enrolment absorbs the sibling-plan state into `ERR_AUTO_UPDATE_NOT_CONSENTED`; on the offer path that case is rule 24's and rule 33 covers only the flag — `routes_firmware.py:192-196` vs `routes_firmware.py:239-248`.
- **§2.9 rule 34 (line 166) — insert** — on both trial endpoints the closed-window test is evaluated before rules 22/23 — `routes_trial.py:84-86`, `routes_trial.py:63-65`.
- **§3.6 (line 301) — insert** — extend with an open window and a non-`ACTIVE`/`PAUSED` trial (terminal included) yields `ERR_INVALID_STATE`, not `ERR_ALREADY_TERMINAL` — `routes_trial.py:65` (no terminal table) + `services.py:43-53`.
- **§3.8 (line 357) — insert** — a declined billing cycle *fails* with `ERR_PAYMENT_DECLINED` while the charge fields, `PAST_DUE` and `dunning_attempts` stay committed; same for a declining retry incl. suspension cascade — `routes_finance.py:133-141`, `routes_finance.py:164-172`.
- **§3.9 (line 373) — revise** — campaign `model` is drawn from the `NEO`/`LINK`/`FLEX` set — `routes_firmware.py:41` + `routes_order.py:17`.
- **§3.9 (line 379) — revise** — manual enrolment's consent predicate spelled out (plan must exist in `ACTIVE`/`TRIALING` with consent true, one error); no campaign-`status` or window precondition — `routes_firmware.py:181-204`.
- **§3.9 (line 381) — revise** — offer's plan gate split in two, in order: plan state → `ERR_DEPENDENT_STATE_NOT_READY` (rule 24), then `firmware_auto_update_enabled` → `ERR_AUTO_UPDATE_NOT_CONSENTED` (rule 33) — `routes_firmware.py:239-248`.

### Pre-edit search log (subject / paths enumerated / wording adjustment)

1. **Timestamp form.** Paths: single formatter `store.iso`, applied to every `datetime` by `store.serialize` (recursing into `pause_intervals`), `resp._request_timestamp`, `routes_test.py:31`; input side is `bodyspec.py:119` → `store.parse_iso`. Adjustment: scoped the claim to what the API *emits* (dropped a planned sentence about accepted request formats, since `parse_iso` accepts offsets/naive/date-only).
2. **Rule 33 consent mapping.** Paths: `routes_firmware.manual_enrollment:192-196`, `offer_rollout:239-248`, `calc.eligible_devices:524-529` (cohort silently *excludes*, raises nothing), `install_rollout` (no plan check), `services.cancel_rollouts_for_device`. Adjustment: added "unless the campaign is a mandatory safety campaign" and confined the statement to the two named endpoints so cohort selection and install are untouched.
3. **Trial-window precedence.** Paths: `create_return_auth:81-86` (stale-version still first), `extend_trial:59-65` (`ERR_VALIDATION` still first), `void_return:195-200` (raises the same error but after the *authorization's* state check), `services.touch_trial`. Adjustment: said "before rules 22 and 23" only (not "before everything"), and dropped "on these two endpoints alone" so `void_return`'s use of the same error is not excluded.
4. **Extend origin set.** Paths: `routes_trial.py:65` is the only `ensure_state` call without a terminal table besides `routes_finance.py:127`; `services.ensure_state` orders rule 23 then 22. Adjustment: prefixed "While the window is still open" so the sentence cannot contradict edit 3 for expired terminal trials.
5. **Error responses with committed writes.** Paths: both `ERR_PAYMENT_DECLINED` sites (`routes_finance.py:141,172`), `_apply_cycle`, `_suspend_effects`, and `app.py` error handlers (no rollback; store is plain dicts). `ERR_DEDUCTIBLE_UNPAID` (the other 402) writes nothing. Adjustment: for the retry case named only `dunning_attempts` + suspension/cascade (the retry path does *not* rewrite the charge fields).
6. **Campaign model enum.** Paths: `routes_firmware.create_campaign:41`, `routes_order.py:17,34,190,232` (order/device/pool share `MODELS`), `calc.eligible_devices:509`. Adjustment: none.
7. **Manual-enrolment preconditions.** Paths: whole `manual_enrollment` body (`ref` → stale-version → consent), `advance_campaign` (which *does* gate on campaign state/window), `in_window`. Adjustment: phrased as "nothing is required of the campaign itself … whatever `status` the campaign holds" rather than enumerating states, and kept the window remark scoped to this endpoint.
8. **Offer preconditions.** Paths: `offer_rollout:233-248`, `install_rollout:259-271` (campaign-`ROLLING` only on the `FAILED` retry branch — deliberately not described), rule 24's existing list. Adjustment: left the campaign-`ROLLING` and maintenance-window clauses verbatim (the window's `ERR_INVALID_STATE` mapping is outside the Step 7 site) and only pinned the plan/consent split and its order.

## Step 9: Complete PRD — 2026-09-01T22:38:00.000Z

Subagent summary (verbatim):

All modules are now covered; the two final edits pin `bodyspec.py`'s body-validation semantics into §2.9 rules 15 and 16.

## File deltas

| | lines | bytes |
|---|---|---|
| `workspace/PRD_FINALIZED.md` (source) | 593 | 142,266 |
| `workspace/PRD_COMPLETED.md` | 593 | 179,560 |
| delta | 0 | **+37,294** |

91 edits total, all in-paragraph (no new sections, no new paragraphs, no line count change): **68 ambiguity-pins**, **23 mismatch-revisions**, touching 69 paragraphs.

## Changes

Global sections:
- §2.3 — insert — ambiguity — blank/unparseable `limit`/`offset` are `ERR_INVALID_PAGINATION`, not treated as absent — resp.py:74-94
- §2.3 — insert — ambiguity — ordering tie-break is server insertion order; declared filters run after owner scoping and before pagination, matched by exact/typed value, undeclared params ignored — store.py:149, common.py:11-38
- §2.4 — insert — ambiguity — `_clock/set_current_utc` persists no row and returns `data.current_utc`; no eager expiry sweep; only `meta.api_request_timestamp` reads wall clock — routes_test.py:21-31
- §2.5 — insert — ambiguity — order retains a non-serialized snapshot of the whole policy row that all later regulatory reads consult; amendment body is the twelve config fields only; retire is idempotent and re-bumps `version` — routes_policy.py:90-133
- §2.9 r15 — insert — ambiguity — explicit `null` == absent (default applies), strict types (bool rejected as int/number), blank-string rule, ISO-8601 parse failure, first-read field wins — bodyspec.py:44-121
- §2.9 r16 — insert — ambiguity — enum membership deferred to `finish()`, so a mistyped field beats an out-of-set value; wrong-typed enum is `ERR_VALIDATION` — bodyspec.py:124-146
- §2.9 r26 — revise — mismatch — `min_age_years` comes from the patient's live policy row, and from the checkout snapshot only on the order path — routes_order.py:20-60
- §2.9 r31 — insert — mismatch — on determination, licensure is tested before rules 22/23/32 — routes_provider.py:128-160
- §2.11 — insert — mismatch — unroutable path → `ERR_RESOURCE_NOT_FOUND` 404; unimplemented method → `ERR_ROLE_NOT_PERMITTED` on **405**, not the catalogue's 403; non-object body → `ERR_VALIDATION` — app.py:36-61

§3.1 Onboarding:
- insert — ambiguity — `state_code` must be exactly 2 already-uppercase chars (no normalization); uniqueness is exact — routes_policy.py:40-74
- insert — ambiguity — patient `age_years` bounds 0-120 with an 18 floor when unresolvable; audiogram/tenure figures only non-negative — routes_policy.py:147-164
- insert — ambiguity — `acknowledge-waiver` gates only on ownership, is accepted from any non-terminal candidacy status and is re-stampable; `DELETE /patients` refuses live orders, then `ERR_ALREADY_TERMINAL` vs `ERR_INVALID_STATE` — routes_policy.py:214-247

§3.2 Screening:
- insert — ambiguity — session create ignores `is_retired`, is accepted from `SCREENING_IN_PROGRESS`/`CANDIDATE_APPROVED`/`PROVIDER_CLEARED` leaving status untouched; `supersedes_session_id` only ever from the body — routes_policy.py:249-282
- insert — ambiguity — four measurements required, `symptom_codes` optional and not reset when omitted, members free-form with seven recognized literals — routes_policy.py:339-396
- insert — ambiguity — submit rejects only `MEDICALLY_DISQUALIFIED` (before the null sweep), any candidacy state otherwise; `min_age_years` from the live policy with an 18 floor — routes_policy.py:339-360
- revise — mismatch — "latest non-invalidated session" includes `DRAFT`/`IN_PROGRESS` (driving 0.0); flag counts sweep all non-invalidated sessions; no session at all scores 0.0 — calc.py:150-180
- insert — ambiguity — invalidate tests provider `ACTIVE` and state licensure before the session's own origin state; supersede semantics at submit time — routes_policy.py:398-425
- insert — ambiguity — findings are stamped for **every** detection (advisory included) in §3.2 table order, with insertion order as tie-break — calc.py:103-140

§3.3 Referral & overrides:
- insert — ambiguity — provider selection skips providers failing the buffered slot geometry rather than double-booking — calc.py:537-570
- insert — ambiguity — referral creation counts advisory findings into `reason_codes`, skips invalidated sessions — routes_provider.py, services.py
- insert — ambiguity — cleared-findings read resolves through `triggering_screening_session_id`, falling back to the latest `SCORED` session — routes_provider.py:119-127
- insert — ambiguity — withdraw refuses an `IN_PROGRESS` fitting session after the referral origin check; retake gated only while `REFERRAL_REQUIRED` with lazy expiry first — routes_provider.py:196-219
- insert — mismatch — override reject imposes no patient-status requirement; counters zeroed directly (findings keep null `cleared_by_referral_id`); wrong-patient → `ERR_RESOURCE_NOT_FOUND`, terminal → `ERR_ALREADY_TERMINAL`, both after SoD — routes_policy.py:479-545

§3.4 Fitting sessions:
- revise — mismatch — the focus date is **sticky** (last booking/attendance transition on the row), not "today"; `utilization_pct` 0.0 when capacity is 0/absent — calc.py:389-416
- insert — ambiguity — `provider_referral_id` mandatory for `REFERRAL_EVALUATION`; for other types `provider_id` mandatory and `device_order_id` optional; provider must be `ACTIVE` — routes_provider.py:220-296
- insert — ambiguity — referral condition maps three ways (`EXPIRED`/terminal/`SCHEDULED`-or-`EVALUATED`), and referral, expiry and reschedule-cap tests precede everything else — routes_provider.py:220-260
- insert — ambiguity — plan chosen is the earliest-created `ACTIVE`/`PAST_DUE`; no-show/cancel report `ERR_PATIENT_MEDICALLY_DISQUALIFIED` and recompute against the abandoned slot's date; exactly 24h remaining counts as late — routes_provider.py:388-470

§3.5 Orders, fit, inventory:
- insert — ambiguity — placement gates only on `MEDICALLY_DISQUALIFIED`; unresolvable policy → `ERR_REFERENCE_NOT_FOUND`, tested with the retired-policy check before body validation — routes_order.py:20-60
- insert — ambiguity — payment simulation requires `PENDING_AUTH` — routes_test.py:34-43
- insert — mismatch — a decline cancels fulfillment only from the three live states, and from `READY_TO_SHIP` also releases the reservation and returns the device to `IN_STOCK` — routes_test.py:44-55
- insert — ambiguity — ship order: flag/payment/device gate order and `ERR_DEPENDENT_STATE_NOT_READY` covering missing or non-`ASSIGNED` device — routes_order.py:135-165
- insert — ambiguity — delivery sets device `WITH_PATIENT`, creates a trial only when absent, and promotes a `TRIALING` plan with a 30-day window at `delivered_at` — routes_test.py:66-91
- insert — mismatch — confirm-fit gate order pins the `CANDIDATE_APPROVED`/`PROVIDER_CLEARED` check *after* the medical/waiver band; earliest-created `IN_STOCK` device, and success with no device when none exists — routes_order.py:94-132
- insert — mismatch — `sku` shape is conventional only: the server enforces non-emptiness and uniqueness, any distinct string is accepted; lookups match the model/dome/tip triple, earliest-created wins — routes_order.py:227-242
- insert — ambiguity — restock requires ≥1; discontinue is idempotent and accepted on an already-discontinued pool — routes_order.py:254-273
- insert — mismatch — cancel accepts `PENDING_AUTH`/`AUTHORIZED`/`CAPTURED` only; payment settles by current value (`VOIDED`, full `REFUNDED` with `retained_cents` 0, `PENDING_AUTH` untouched); inventory/device/trial/auth/plan side effects and their no-ops — routes_order.py:168-181, services.py:426-447

§3.6 Trial, returns, exchanges:
- insert — ambiguity — order-summary returns the plain order row with `open_balance_cents` refreshed, no sub-objects, no `version` bump — routes_order.py:85-91
- insert — ambiguity — `paused_days`/`effective_end_utc` circularity resolved by fixpoint iteration — calc.py:222-248
- insert — ambiguity — per-grant bound plus a cumulative 30-day cap checked before expiry sweep and status test — routes_trial.py:52-69
- insert — ambiguity — OCC guard evaluated first, then `ACTIVE`-only trial, then order `SHIPPED`; `rma_code` minted `RMA-%06d` from a counter — routes_trial.py:73-109, store.py:52
- insert — ambiguity — inspection credits the pool the unit was actually dispatched from (post-exchange pool first), and the deadline test follows the `ISSUED` origin check — routes_trial.py:151-171
- insert — mismatch — settlement's only precondition is order existence + `CAPTURED`, and the payment fork is decided by `refunded_cents == captured_cents`, with `retained_cents` forced to 0 — routes_trial.py:174-187, services.py:451-483
- insert — ambiguity — waive-restocking precondition order and `ERR_INVALID_STATE` (not `ERR_ALREADY_TERMINAL`) for terminal authorizations — routes_trial.py:212-236
- insert — mismatch — exchange: target-pool existence resolved first; trial/plan failure yields a 201 `REJECTED` row, while a depleted pool is a hard `ERR_INVENTORY_POOL_DEPLETED` unless `allow_backorder` — not the other way round; `SAME_CONFIGURATION` is never written — routes_trial.py:240-307
- insert — mismatch — ordinal computed before the accept/reject decision and reused; fee drawn as the lesser of fee and credit; confirm skips the second movement when source is target; cancel origin sets are exactly one per role and refund the fee **in full** — routes_trial.py:240-402, calc.py:472-485

§3.7 Repairs & warranty:
- insert — ambiguity — repair's patient/plan resolved through the device's order, null when unassigned; no device-status gate at creation — routes_repair.py:26-39
- insert — ambiguity — SLA credit treats `SUSPENDED`/`CANCELLED` plans as no plan; `TRIALING`/`PAST_DUE` still earn their tier — services.py:514-519, calc.py:489-501
- insert — ambiguity — `pauses_trial` evaluated after expiry sweep and frozen at creation — routes_repair.py:26-39
- insert — ambiguity — kit dispatch and receipt both require `WITH_PATIENT` on `ERR_DEPENDENT_STATE_NOT_READY` terms; credit uses the tier at receipt; pause attempted only for a genuinely `ACTIVE` trial — routes_repair.py:77-118
- insert — mismatch — resolution's deductible test is satisfied by **any** claim on the same `device_id` with `deductible_paid_cents > 0`, regardless of status/kind/ordinal or amount — routes_repair.py:131-160
- insert — ambiguity — closure ends open pause intervals at the clock and skips resume silently when not `PAUSED`; patient may cancel only `KIT_REQUESTED`, operator also `KIT_SENT` — routes_repair.py:199-209, services.py:522-547
- insert — mismatch — claim filing resolves device then originating repair (both `ERR_REFERENCE_NOT_FOUND`) with no status gates; triage requires a non-`RETIRED` device, then `claim_ordinal` before `device_age_months`; denial branch runs first with the reason stored unverified — routes_repair.py:256-344
- insert — ambiguity — calendar `months_between` anchor rule; cap read from the patient's **current** policy (unresolvable → 0) and tested before warranty; replacement minted `RPL-<seq>`, firmware `4.0.0`, null warranty/shipped; deductible accumulates uncapped; fulfilment demands exact payment and `RETURNED_TO_PATIENT` — routes_repair.py:286-399, calc.py:360-387

§3.8 Plans & reimbursement:
- insert — ambiguity — enrolment resolves patient then order, then ownership; no other gate — routes_finance.py:38-57
- insert — ambiguity — tier change with a null `cycle_end_utc` stores the charge unprorated — calc.py:351-359
- insert — ambiguity — tier change accepted from `TRIALING` too, with the OCC guard before the status test — routes_finance.py:78-98
- insert — mismatch — billing run requires `ACTIVE` only (all others `ERR_INVALID_STATE`), plus a closed window; null window also `ERR_INVALID_STATE` — routes_finance.py:116-129
- insert — ambiguity — `pay_from_credit` insufficiency precedes decline handling; a decline fully covered by credit is not a decline; cycle advance and credit consumption — routes_finance.py:130-144
- insert — ambiguity — dunning cap 3 after the `PAST_DUE` check; retry applies no cycle on failure and takes no `pay_from_credit` — routes_finance.py:147-172
- insert — ambiguity — reinstate rewrites the window from the clock keeping `cycle_ordinal`, refuses a `RETURN_SETTLED` trial after sweeping it; no trial is fine — routes_finance.py:182-198
- insert — ambiguity — patient cancels only from `ACTIVE`/`PAST_DUE`; operator also `SUSPENDED`/`TRIALING` — routes_finance.py:201-211
- insert — mismatch — claim create: fixed check order, appeal **inherits** subject kind and all references overriding the body, create-time duplicate rejected outright (row deleted), extra doc codes accepted as free strings — routes_finance.py:234-298
- insert — ambiguity — submit re-tests duplicate then documentation then subject existence, `DEVICE_ORDER` needing `CAPTURED`/`PARTIALLY_REFUNDED`; info-request cap 2 with codes recorded nowhere; supply-info merge/overwrite semantics — routes_finance.py:322-396
- insert — ambiguity — decide runs SoD **before** the `UNDER_REVIEW` check; denial reason required only on the deny branch; pay requires a recorded approver and non-zero allocated benefit; `ERR_APPEAL_ALREADY_EXISTS` from any child claim — routes_finance.py:399-452

(§3.8 is nine paragraphs; the last two bullets each fold two adjacent paragraphs.)

§3.9 Firmware:
- insert — ambiguity — campaign defaults (`batch_size` 3, `max_concurrent_installs` 2, `is_mandatory_safety` false), duplicate `campaign_code` → `ERR_DUPLICATE_KEY` — routes_firmware.py:36-60
- insert — mismatch — the three counters are always recomputed: `rollout_count` excludes `CANCELLED_INELIGIBLE`, the failure rate reads *current* `FAILED` status so a rollback lowers it — services.py:182-197
- insert — ambiguity — schedule's three conditions in order after the `DRAFT` check, first two `ERR_VALIDATION` — routes_firmware.py:78-91
- insert — mismatch — `selection_rank` restarts at 1 each advance (batch-scoped, not campaign-scoped); window/concurrency tests precede cohort selection; empty cohort leaves `SCHEDULED`; null `warranty_expires_at` sorts as the current clock — routes_firmware.py:94-119, calc.py:502-536
- insert — ambiguity — manual enrolment: device must resolve, OCC guard next (ahead of consent), rank from the current `rollout_count`, and no device-state gate at all — routes_firmware.py:181-204
- insert — ambiguity — offer requires a `ROLLING` campaign and open window, then plan state, then consent; install's `OFFERED` path asks nothing of campaign status, window or attempts; unresolvable campaign skips the concurrency test — routes_firmware.py:229-275
- insert — ambiguity — `failure_code` defaults to `TIMEOUT`; the auto-pause fires only while `ROLLING`; the `FAILED` retry path checks `ROLLING` then the 3-attempt cap and never re-tests the window — routes_test.py:112-144, routes_firmware.py:254-275
- insert — mismatch — rollback needs three attempts **or** `CHECKSUM`, and opens a `FIRMWARE_BRICK` repair only for `CHECKSUM`/`POWER_LOSS`; the mandatory-safety exemption spares `OFFERED` rollouts on only two of the five cancellation paths; abort is accepted from `SCHEDULED`, `ROLLING` **and** `PAUSED` (with `rollout_count` 0 required from `SCHEDULED`) and recomputes counters; resume tests rate then window — routes_firmware.py:132-178, 278-299, services.py:322-340

§4 Endpoints:
- §4 (row at line 439) — revise — mismatch — order-summary row corrected to the recompute-and-return-order-row behavior — routes_order.py:85-91

Machine cross-checks (all clean): §4 endpoint set 127/127 with zero diffs either way; §4 authorized-role column 0 diffs of 127 vs `authorize(...)`; §5 catalogue 65/65 ids with no HTTP-status differences vs `errors.ERROR_STATUS`. §2.1, §2.2, §2.6, §2.7, §2.8 and §2.10 were reviewed and already pinned uniquely, so they carry no edits.
