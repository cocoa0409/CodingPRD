# Worklog — task_2705_app_store_submission_review_compliance

## Step 1: Create task directory — 2026-09-04T08:58:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2705_app_store_submission_review_compliance` and its `workspace/` subdirectory. Index 2705 was pre-assigned by the invocation; no scan of `./tasks/` was performed.

## Step 2 (attempt 1, FAILED): Generate scaffold — 2026-09-04T09:43:00.000Z

A single scaffold subagent asked to produce all three artifacts died with `max_output_tokens` (64000 output-token cap on one assistant message) and wrote **zero** files. Orchestrator decision (no user available to consult): split Step 2 into three subagents — one per output file — each under a hard "~200 YAML lines per tool call, one append per assistant message" protocol. 2a (SCAFFOLD.yaml) runs first because 2b/2c must read it; 2b and 2c then run concurrently.

## Step 2a: Generate SCAFFOLD.yaml (§1.0–§1.7) — 2026-09-04T10:18:00.000Z

Done.

**File:** `/home/ubuntu/github/CodingPRD/tasks/task_2705_app_store_submission_review_compliance/SCAFFOLD.yaml` — 3148 lines, §1.0–§1.7 only (no `scaffold_difficulty_design` / `scaffold_corner_design` keys).

**Counts**
- Entities: **15** (PublisherAccount, SigningCredential, AppRecord, GuidelineRule, FeatureMapping, Submission, MetadataLocale, BehaviorFinding, RejectionReason, AppealRequest, ExpediteRequest, ReviewCapacityWindow, RolloutPlan, CommerceItem, ImpactAssessment)
- State machines: **12** over 11 entities, **87 transitions** (AppRecord carries two independent dimensions: `listing_state` + `distribution_state`)
- Concurrency rules: **4** (OCC only — AppRecord x2 -> `ERR_STALE_APP_RECORD_VERSION`, PublisherAccount x2 -> `ERR_STALE_PUBLISHER_ACCOUNT_VERSION`, all 412)
- Calculation rules: **13** (incl. two dual-variant: `disclosure_accuracy_score`, `standing_score`; combinatorial modes a/b/c: age-rating tie-break ladder, per-line-round-then-sum commission, pinned 6-step forward-pass priority score; three conserved quantities: expedite credits, audience share pct, review slots)
- Validation rules: **43** across a strict 15-tier priority ladder (10 header -> 75 fiscal) with explicit PRIORITY PAIR notes at 15v25, 30v35, 40v55, 70v75
- Endpoints: **80** (flat root-level collections, `api_prefix: "/"`, includes `POST /_clock/set_current_utc` with default clock `2026-08-01T00:00:00Z`)
- Error codes: **81**
- RBAC roles: **7** — PublisherAdmin / ReleaseManager / ComplianceOfficer (`entity_backed:PublisherAccount`), PlatformReviewer / PlatformAppealBoard / PlatformPolicyAdmin / Auditor (`opaque`)

**Verification**
- `yaml.safe_load` parses cleanly; 14 top-level keys (adds `global_constants` with 17 pinned constants).
- Cross-reference sweep: 0 error codes referenced-but-uncatalogued, 0 catalogued-but-unused, 0 endpoint roles undeclared, 0 declared roles unused, 0 hits on forbidden race vocabulary.
- FK reverse-reachability (lint check f) run directly against the module: 80 endpoints parsed, 23 FKs, 15 entity collection segments derived, **0 violations**.
- `scaffold_lint.py <task_dir>` cannot complete an end-to-end run yet: it requires `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml`, which are the other two subagents' deliverables. Re-run the full linter once those land.

## Step 3: Copy shared files — 2026-09-04T10:26:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_2705_app_store_submission_review_compliance/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T11:05:00.000Z

Orchestrator note: Step 4 was launched concurrently with Steps 2b/2c (the two design indices) rather than after them. This is safe and does not violate the skill's sequencing — Step 4's only input is SCAFFOLD.yaml, which Step 2a had already completed, and the doc generator is explicitly forbidden from reading either design index. Running it in parallel recovered the wall-clock lost to the failed Step 2 attempt 1.

Subagent summary (verbatim):

The PRD is complete.

**File:** `/home/ubuntu/github/CodingPRD/tasks/task_2705_app_store_submission_review_compliance/workspace/PRD.md` — **484 lines**, ends at the last row of the §5 error table (a real section boundary, no audit footer).

**Section list**
- §1 Introduction
- §2 Global Specifications: 2.1 RBAC · 2.2 API Response Structure (verbatim canonical block, confirmed byte-identical) · 2.3 Pagination · 2.4 Identity/Timestamps/Revision Counters · 2.5 The Logical Clock · 2.6 Revision Guarding · 2.7 The Rejection Ladder · 2.8 Compliance Posture · 2.9 Program Standing · 2.10 Segregation of Duties · 2.11 Precision & Conserved Quantities · 2.12 Addressing and the One Nested Read
- §3 Business Logic: 3.1 Enrollment/membership/enforcement · 3.2 Signing material & compromise cascade · 3.3 App listing's two state dimensions · 3.4 Guideline corpus & publication cascade · 3.5 Impact assessments · 3.6 Submission composition & metadata locales · 3.7 Age rating, privacy disclosure, self-review report · 3.8 Reviewer capacity, queue entry, priority forward pass, expedite · 3.9 Review, decision, rejection response, appeal, standing · 3.10 Staged release · 3.11 Commerce & settlement
- §4 Endpoint table (4 columns, 80 rows)
- §5 Error table (2 columns, 81 rows)

**Coverage cross-check (all confirmed present)**: 15 entities · 12 state machines (every from/to state value appears backticked in §1–3) · 4 concurrency rules · 13 calculations · 43 validation rules (all 81 error identifiers appear in the §1–3 prose, not only in the table) · 80 endpoints · 81 error codes · 7 roles · 17 constants (each value rendered in prose). Nothing could not be fitted.

**Hard Contract reports** (kept out of the file, per spec):
- **Contract 1 Field-Name Coverage — PASS.** 178 required identifiers (165 entity field names + 13 non-field request/query/path identifiers: `action`, `current_utc`, `expected_app_record_version`, `expected_publisher_account_version`, `expedite_request_id`, `limit`, `listing_action`, `offset`, `outcome`, `paid_through_at`, `period_label`, `rejection_reasons`, `to_phase_index`). 178/178 appear verbatim in backticks; 0 missing.
- **Contract 2 Rule Coverage — PASS.** All 4 OCC rules with write endpoint + `expected_<parent>_version` + error id + 412; every state transition with from/to, preconditions paired to error ids, and full side-effect cascades (four-hop compromise, four-hop rule publication, four-hop rejection, rollback branches); all 13 calculations with full formulas, constants, precision and pinned evaluation/rounding order (priority forward pass, sum-then-divide disclosure, round-per-line-then-sum commission); all sibling-branch divergences rendered symmetrically (REJECT vs METADATA_REJECT, PHASED vs IMMEDIATE start, `halt_distribution` true/false, three appeal outcomes, two disclosure variants, two standing variants, provisional vs final).
- **Contract 3 §3 Path Purity — PASS.** 1308 backticked tokens in §3; 0 begin with `/`, 0 are bare HTTP methods, 0 combine method+path. §1–2 are also path-free; the HTTP contract appears only in §4.

Two corrections were made against the scaffold while writing: the `Submission.state` enum and several submission field names had been drafted from a stale digest (now the real 12 values and `pre_review_blocking_reasons` / `disclosure_accuracy_score_provisional` / `_final` / `effective_review_deadline_at`), and three invented error codes (`ERR_DUPLICATE_RULE_VERSION`, `ERR_DUPLICATE_FEATURE_MAPPING`, `ERR_DUPLICATE_LOCALE`, `ERR_SUBMISSION_NOT_EDITABLE`) were replaced — the scaffold has no dedicated codes for those uniqueness breaches, so the PRD routes them to `ERR_VALIDATION` (and duplicate locale to `ERR_DUPLICATE_PRIMARY_LOCALE`, which the scaffold's own condition text covers).

**Orchestrator truncation check (per the known doc-generator failure mode): PASS.** `tail -12 PRD.md` ends mid-table-body at the final `ERR_REVENUE_ALREADY_REPORTED | 409 |` row — a real structural boundary, not a mid-sentence cut — and `grep '^#'` confirms all five top-level sections (§1 Introduction, §2 Global Specifications, §3 Business Logic, §4 API Endpoint Specifications, §5 Error Handling) plus all 12 §2 and all 11 §3 subsections are present. No regeneration needed.

## Step 2b: Generate SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8) — 2026-09-04T12:38:00.000Z

Done.

**File:** `/home/ubuntu/github/CodingPRD/tasks/task_2705_app_store_submission_review_compliance/SCAFFOLD_DIFFICULTY_DESIGN.yaml`

- **Line count:** 1844
- **Rules covered:** 9 of 9 (`dual_variant_calc` 3, `combinatorial_formula` 3, `non_linear_state_machine` 3, `transitive_cascade` 3, `priority_pair_validation_conflict` 3, `boundary_precision_check` 4, `cross_entity_state_dependency` 3, `resource_temporal_overlap` 3, `compensating_invariant` 3)
- **Non-stub instances:** 28 — every one has `grounds`, a falsifiable one-sentence `distinguishing_aspect`, and a `test_recipe` with non-empty `setup_api_calls`, `trigger`, and `assert` built from empty-DB-reachable structured calls
- **YAML parse:** `yaml.safe_load` succeeds; top-level keys `['scaffold_difficulty_design']` (single key, nothing else in the file)

Additional automated checks I ran against the parsed document, all clean: no keys outside the §1.8 schema at rule / instance / `test_recipe` / call level; all 28 instance names unique; every `${var}` in a call path, payload, or assert is bound by an earlier `captures:` in the same instance (no unbound references).

Two defects found and fixed during final verification:
- A stray instance-level `setup: []` key (not in the §1.8 schema) emitted in the last `compensating_invariant` instance — removed.
- **Root cause of the only parse failure:** unquoted JSONPath capture values. `captures: { rr1_id: $.data[0].id }` is invalid inside a YAML flow mapping (the `[` after a plain scalar aborts the mapping). All 370 capture expressions (`$.data.id`, `$.data.version`, `$.data[0].id`, etc.) are now quoted as `"$.data..."`, which parses and keeps the values byte-identical as strings.

Final three instances added this session: `rollback_cooldown_one_sided_strict_buffer` (ROLLED_BACK predecessors swap the closed-interval test for a one-sided strict 72h buffer — accepted at exactly `terminated_at + 72h` even though that instant is inside the rolled-back plan's original interval, then rejected again once a SCHEDULED plan occupies it), `review_slot_conservation_queue_then_withdraw` (withdrawal restores `slots_available` to the exact pre-queue integer; APPROVE moves reserved->consumed and is never compensated), `expedite_credit_conservation_grant_consume_then_refund` (GRANTED and CONSUMED both count, REQUESTED and REFUNDED never do, so one withdrawal takes remaining 0 -> exactly 2), and `audience_share_conservation_advance_pause_resume_then_rollback` (shares conserved at 100.00 including while PAUSED; RESUME re-stamps `phase_entered_at` so the next advance hits `ERR_PHASE_DWELL_NOT_MET`).

I did not read or write `SCAFFOLD_CORNER_DESIGN.yaml`, and I did not access any other `tasks/task_*/` directory.

## Step 2c: Generate SCAFFOLD_CORNER_DESIGN.yaml (§1.9) — 2026-09-04T13:52:00.000Z

Done.

**Output file**: `/home/ubuntu/github/CodingPRD/tasks/task_2705_app_store_submission_review_compliance/SCAFFOLD_CORNER_DESIGN.yaml`
- **7255 lines**, single top-level key `scaffold_corner_design` (YAML parse verified: `['scaffold_corner_design']`).
- **222 instances, zero stubs** — every instance has `name`, `claim_type`, `grounds`, a one-sentence falsifiable `distinguishing_aspect`, and a complete `test_recipe` (`setup`, `setup_api_calls`, `trigger`, `assert`).

**Section coverage (all 9 §1.9 sections)**: entities 21, state_machines 88, calculations 41, validations 31, endpoints 11, errors 6, rbac 11, cross_cutting_complexity_layers 11, consistency_model 2.

**Mechanical validation run**: no duplicate instance names; every `${var}` in every call is minted by an earlier `captures:` in the same recipe (0 undefined); every `setup_api_calls`/`trigger` entry carries `call` + `as`; no keys outside the §1.9 schema; all aliases resolve (YAML would have failed otherwise). All **81** real `ERR_*` codes in SCAFFOLD.yaml §1.6 appear in the index (the only unmatched token is the envelope placeholder `ERR_XXX`). Output was appended in <=200-line chunks per the size protocol; a recurring 12-space `claim_type` indent slip was caught and fixed by `sed` after the last append.

**Notable design choices**: shared per-state chain anchors (`CH_DRAFT` ... `CH_ITEM_APPROVED`) plus ~60 per-call anchors keep every recipe reproducible from an empty DB with no wall-clock waits; formula-derived numerics are pre-computed literals (e.g. disclosure provisional 0.9500 vs final 0.4800 with a 0.4700 delta; standing 88.00 -> 94.00 -> 97.00 -> 100.00 rolling against a pinned 88.00 lifetime; impact_severity 6.00 at exposure 1.5; index 0.00/12.50/25.00/50.00/100.00).

**Scaffold problems found while grounding instances** (worth relaying to whoever finalizes SCAFFOLD.yaml):
1. Priority-60 `ERR_REMEDIATION_INCOMPLETE` is masked on **every** endpoint in its own `applies_to` (R4/F2 always make the posture non-OPEN so priority 40 answers first); its only reachable home is `POST /impact-assessments/{id}/assess` action `MARK_REMEDIATED`, which is priority-40 exempt. Encoded there.
2. Priority 70 declares a "PRIORITY PAIR (70 vs 75)" between `ERR_APPEAL_WINDOW_EXPIRED` and `ERR_STANDING_TOO_LOW`, but priority 75's `applies_to` is expedite-only — that pair can never co-occur.
3. `POST /review-capacity-windows/{id}/close` says reserved submissions "may still be claimed and decided", while priority 70 requires the assigned window to be OPEN — a direct contradiction. I targeted only the unambiguous *elapsed-interval* case.
4. `report-revenue` appends `period_label` to the account-level `settlement_finalized_periods` and `ERR_REVENUE_ALREADY_REPORTED` fires on that list, so only one CommerceItem per account per period can ever report — multi-line settlement and the documented round-per-line-then-sum divergence in `GET /app-records/{id}/commerce-settlement` are unreachable.
5. Pre-review code order names `SCREENSHOT_SET_EMPTY` while priority 60 names `SCREENSHOT_SET_INCOMPLETE`.
6. No error code exists for a duplicate `FeatureMapping` (app, rule, feature_code) triple, though the uniqueness constraint is declared; that instance asserts only "4xx and no second row".
7. `derived_age_rating` band 4 is unreachable given the answer-to-band mapping.

## Step 2 post-check: scaffold_lint.py remediation (orchestrator) — 2026-09-04T14:05:00.000Z

Ran the skill's own `scaffold_lint.py` against the completed triple (5215 calls scanned across 28 §1.8 + 222 §1.9 instances). First run: **37 violations**. Orchestrator triaged and fixed the three genuinely-defective classes itself rather than re-spawning generators:

1. **(a) malformed call string ×5** — all in §1.8 `priority_pair_validation_conflict / header_role_tenancy_existence_schema_ladder`, whose five triggers had header/tenancy prose stuffed inside the `call` string (`"POST /submissions/{id}/queue (X-Publisher-Account-Id: ${acct_a_id})"`). A downstream test generator parses `call` as `METHOD /path`, so the prose would have broken it. Moved every parenthetical into a new `note:` field and reduced `as: "StoreSuperAdmin (unknown role name)"` to `as: StoreSuperAdmin`. Assertions untouched — they already carried the same explanation.
2. **(e) OCC version literal ×1** — §1.9 `validations / two_unknown_body_references_report_the_first_declared_one` hardcoded `expected_app_record_version: 1`. Added the existing `*c_app_reread` anchor to its setup chain and switched the payload to `${app_v2}`, so the version comes from a server response and cannot go stale behind a cascade.
3. **(c) schema violation in a SETUP call ×2 (one call)** — §1.9 `state_machines / immediate_release_mode_start_jumps_straight_to_completed_and_fully_released` built its `&c_plan_imm` anchor with `rollout_mode: "IMMEDIATE"` and no `app_record_id`. §1.5 declares the field as `mode` and requires `app_record_id`. This one mattered most: a broken *setup* call makes the whole recipe unreachable (unlike a broken trigger, which is the point of the test). Fixed to `mode:` + added `app_record_id: "${app_id}"`.

Final run: **32 violations, and `location:` is `trigger` for all 32** (6 role-not-allowed, 10 undeclared payload key, 16 missing required field). These are correct-by-design negative tests — an RBAC-denial instance MUST call with a role §1.5 forbids in order to earn `ERR_ROLE_NOT_PERMITTED`, and a schema-failure instance MUST send a malformed body to earn `ERR_VALIDATION`. The linter checks call legality and cannot see test intent, so it flags the deliberate probe. **Decision (no user available): accept these 32 and proceed.** The discriminator applied was `location`: zero violations now remain in any `setup_api_calls` chain, so every recipe is reachable from an empty DB. Both design files re-verified to parse with `yaml.safe_load` after the edits.

## Step 6: Generate implementation — 2026-09-04T16:30:00.000Z

Orchestrator note on launch sequencing: Steps 5 and 6 were intended to go out in a single assistant message so the impl generator would be *physically* unable to read `test_suite/`. They were in fact issued in two back-to-back messages. Before launching Step 6 the orchestrator verified by `ls` that the task root still contained only `SCAFFOLD*.yaml`, `worklog.md` and `workspace/` — i.e. neither `test_helpers/` nor `test_suite/` existed yet — so the impl generator did spawn with the same physical isolation, and its prompt additionally forbade reading either directory. Both then ran concurrently.

Subagent summary (verbatim):

Implementation complete and verified. Both smoke servers were terminated by port (`fuser -k 18705/tcp`, `fuser -k 18706/tcp`) — no pattern kills were used — and `__pycache__` was removed so the delivered tree is source-only.

## Files (`/home/ubuntu/github/CodingPRD/tasks/task_2705_app_store_submission_review_compliance/workspace/implementation/`)

| file | lines | role |
|---|---|---|
| `start.sh` | 10 | fresh-process launcher, honours `$PORT` |
| `requirements.txt` | 1 | `flask` |
| `app.py` | 54 | app factory, blueprint registration, 400/404/405 handlers -> `ERR_VALIDATION` |
| `common.py` | 512 | in-memory store, 17 pinned constants, envelope, logical clock, `@endpoint` header/role/tenancy ladder, `resolve`, `paginate`, `scope_rows`, `touch`, Decimal helpers |
| `valid.py` | 209 | schema layer (`req_*`/`opt_*`, `check_unknown`) emitting priority-22 `ERR_VALIDATION` in declaration order |
| `calc.py` | 607 | all 13 calculations (compliance index, posture, dual-variant standing, disclosure score, commission, settlement, capacity counters, expedite ledger, share pairs) |
| `flows.py` | 268 | posture gate, program gate, SoD, rejection cascade, release slot, plan pausing, clock sweep |
| `routes_accounts.py` | 329 | 13 endpoints |
| `routes_apps.py` | 188 | 6 |
| `routes_guidelines.py` | 318 | 12 |
| `routes_submissions.py` | 770 | 15 |
| `routes_reviews.py` | 595 | 21 |
| `routes_rollouts.py` | 267 | 7 |
| `routes_commerce.py` | 201 | 6 |
| **total** | **4329** | |

**80 of 80 endpoints implemented**, confirmed by walking Flask's `url_map` (13+6+12+15+21+7+6 = 80). Storage is pure Python dicts; nothing is seeded at boot; `py_compile` is clean on every module.

## Smoke results (fresh boots, ports 18705/18706, all green)

- Envelope/pagination: empty list -> 200 `response_type: "array"`, `total_count 0`, `limit 10`, timestamp rendered from the logical clock (`2026-08-01T00:00:00.000Z`); `limit=0` -> 422 `ERR_VALIDATION`; no headers -> 400 `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
- Happy path: account -> DISTRIBUTION_CERT -> profile activate -> app record -> rule publish -> feature mapping (`risk_weight 4`) -> self-review PASS -> posture `OPEN`, index `100.00`.
- Capacity: window 201 with 5 slots; a second intersecting window of 6 -> `ERR_REVIEW_POOL_OVERSUBSCRIBED` ("aggregate concurrent capacity 11").
- Review chain: submission 201 -> locale 201 -> age rating -> privacy disclosure provisional `1.0000` -> pre-review `passed true, []` -> queue `WAITING_FOR_REVIEW/NORMAL`, deadline `2026-08-03` -> claim `IN_REVIEW` -> REJECT -> reason response.
- Appeals: file 201 `SUBMITTED`; second filing -> `ERR_APPEAL_ALREADY_OPEN`; board-review -> `BOARD_REVIEW`; decide `OVERTURNED` ratio `1.0` -> submission back to `APPROVED`, cited rule's mapping restored FAILED->`IN_PROGRESS` (index correctly fell to 25.00 -> posture `RESTRICTED` until re-attested).
- Rollouts (second pass, after re-passing the mapping to `OPEN`): plan 201 `projected_end_at 2026-08-10` (start + 7x24h); overlapping closed interval -> `ERR_ROLLOUT_WINDOW_CONFLICT`; start -> `PHASE_ACTIVE` 1.00/99.00; advance too early -> `ERR_PHASE_DWELL_NOT_MET`; skip to phase 3 -> `ERR_PHASE_SEQUENCE_INVALID`; after the clock +24h advance -> phase 1, 2.00; PAUSE -> `PAUSED`; RESUME -> `PHASE_ACTIVE` with dwell restarted; rollback (halt) -> `ROLLED_BACK`, shares 0/100, `rollback_count 1`, `live_submission_id null`, app `distribution_state ROLLED_BACK`.
- Commerce: item 201 -> submit `SUBMITTED` -> review APPROVE -> `commission_rate_applied 0.15` (SUBSCRIPTION, retention 12 caps the 0.30 rate) -> report-revenue 10001c -> `commission_cents 1500` (ROUND_HALF_UP) -> duplicate report -> `ERR_REVENUE_ALREADY_REPORTED`; settlement `2026-Q3` -> 1 line, gross 10001, commission 1500, net 8501.
- Standing: `standing_score_rolling_365 100.0`, `standing_score_lifetime 100.0`, `expedite_credits_remaining 2`, `credit_total 3.0`.
- Guards: expedite GRANT on an `APPROVED` build -> `ERR_INVALID_SUBMISSION_STATE`; a CRITICAL behaviour finding flips app posture to `FROZEN` immediately; clock backwards -> `ERR_CLOCK_NOT_MONOTONIC`.

## Places PRD.md was silent — interpretation chosen

1. `risk_weight` on a feature mapping is derived server-side from the rule's `severity_weight`; a client-supplied value is accepted and ignored.
2. `POST /feature-mappings` is restricted to `ComplianceOfficer` only (PRD names the attester role but not the creator role).
3. The prose-only `ERR_INVALID_RULE_STATE` is not in the error catalogue; `ERR_INVALID_GUIDELINE_STATE` is used for guideline-rule state refusals.
4. Signing-credential freshness: exactly `ACTIVE` is required to activate a compliance profile; `{ACTIVE, EXPIRING_SOON}` is accepted at submission create / queue / claim.
5. Pre-review blocking-reason array follows the literal PRD sentence order; queue-time hard errors follow the ladder bands 55 -> 60 -> 65.
6. Report code `SCREENSHOT_SET_EMPTY` (advisory) is distinct from hard error `ERR_SCREENSHOT_SET_INCOMPLETE` (listing/queue refusal).
7. An app that never recorded an age rating counts as *understated* rather than as absent.
8. `PlatformPolicyAdmin` may drive only `DELIST`; posture and program gates apply to all four listing actions.
9. Version bumps: explicit PRD statements honoured; derived recomputes bump only on a real value change; refusals and reads never bump.
10. `api_request_timestamp` is rendered from the logical clock, not the wall clock.
11. A provisional disclosure score with a null `pre_review_checked_at` is `1.0000`.
12. Standing-summary counters use the rolling-365 scope; `postures_frozen_count` counts apps newly transitioned to FROZEN by the clock sweep; a clock jump past `not_after` counts only as expired (not also as a lapse event).
13. Settlement line shape: `{commerce_item_id, reference_name, item_type, reported_gross_cents, commission_rate_applied, commission_cents}`; the settlement object also returns `period_label`, `line_count`, `gross_cents_total`, `commission_cents_total`, `net_cents_total`.
14. `reason_code` on report-compromise / submission withdraw / appeal withdraw is validated but not persisted (no such field exists on those entities).
15. A duplicate `locale` on one submission reuses `ERR_DUPLICATE_PRIMARY_LOCALE`.
16. Appeal filing checks `ERR_APPEAL_ALREADY_OPEN` *before* the `REJECTED` state check; there is no standing floor on appeals (`ERR_STANDING_TOO_LOW` is expedite-only).
17. Expedite decide order: expedite state -> submission state (GRANT branch only) -> SoD -> quota -> standing.
18. Appeal decide order: appeal state -> subset `ERR_VALIDATION` -> SoD.
19. Rollout create order: OCC -> posture -> program -> mode mismatch -> interval/cooldown conflict; the 72h cooldown applies only against `ROLLED_BACK` plans whose `halt_distribution` is true.
20. Commerce `rejection_note` requirement is enforced after the state and SoD checks.
21. Flask-level 404/405/malformed-JSON all return `ERR_VALIDATION` in the standard error envelope.

## Unit test generation (test_helpers/ + test_suite/)

- `test_helpers/`: 9 modules (api_client, api_errors, assertions, constants, factories,
  fixtures, test_users, types, barrel `__init__`), 2430 lines.
- `test_suite/`: conftest.py plus 18 test modules, 14149 lines, 362 tests collected.
  Queue A (§1.8 difficulty): 98 tests over all 28 instances, every instance >= 2 tests.
  Queue B (§1.9 corner): 264 tests over 221 of 222 instances.
- Every test carries exactly one `Design: Difficulty/<rule_id>/<name>` or
  `Design: Corner/<section>/<name>` line as the last docstring line; all 249 tags resolve
  to real design instances (audited by AST + yaml.safe_load).
- Skipped instance (PRD-first filter, unique-derivability):
  `Corner/endpoints/report_mode_pre_review_returns_two_hundred_with_every_blocking_reason_in_priority_order`.

## Step 5: Generate unit tests — 2026-09-04T19:12:00.000Z

Subagent summary (verbatim):

Done. The unit-test infrastructure and full test suite for `task_2705_app_store_submission_review_compliance` are complete and verified.

## Output (all under the TASK ROOT, nothing written to `workspace/`)

`/home/ubuntu/github/CodingPRD/tasks/task_2705_app_store_submission_review_compliance/test_helpers/` — 9 modules, 2430 lines: `__init__.py` (48, barrel), `api_client.py` (310), `api_errors.py` (132), `assertions.py` (293), `constants.py` (125), `factories.py` (221), `fixtures.py` (543), `test_users.py` (97), `types.py` (661).

`.../test_suite/` — `conftest.py` (44) plus 18 test modules, 14149 lines total: `test_01`(317) `test_02`(289) `test_03`(466) `test_04`(392) `test_05`(408) `test_06`(601) `test_07`(481) `test_08`(344) `test_09`(502) `test_10`(827) `test_11`(3526) `test_12`(1577) `test_13`(1467) `test_14`(480) `test_15`(312) `test_16`(942) `test_17`(1056) `test_18`(118).

## Tests emitted: 362 collected

- **Queue A (§1.8 difficulty):** 98 tests over **28/28** instances; every instance has >=2 tests.
- **Queue B (§1.9 corner):** 264 tests over **221/222** instances (>=1 each).
- 249 distinct `Design:` tags; an AST + `yaml.safe_load` audit confirms every test has **exactly one** tag, it is the **last docstring line**, and it resolves to a real instance — 0 problems. No `skip`/`xfail` markers anywhere.

## Verification run
`python3 -m py_compile` clean on all 28 files; `python3 -m pytest test_suite --collect-only -q` -> **362 tests collected, 0 errors**; `pyflakes` clean (no undefined names, no unused imports in `test_suite/`).

Three latent import bugs found and fixed by the pyflakes/collect sweep (they would have been Stage-2 collection failures): `setup_released_ios` missing from `test_08` and `test_09` imports, `set_questionnaire` missing from `test_13`, `make_appeal_board_headers`/`make_policy_admin_headers` missing from `test_11`, and `DEFAULT_*_ID` constants were never re-exported from the `test_helpers` barrel (added).

## Skipped instances (PRD-first filter)
- `Corner/endpoints/report_mode_pre_review_returns_two_hundred_with_every_blocking_reason_in_priority_order` — **unique-derivability**: the PRD's tie-break sequence for `pre_review_blocking_reasons` cannot be reconciled with the ascending-rule-priority ordering for the design's asserted array, so the exact output is not uniquely derived.

## Design-vs-PRD divergences resolved PRD-first (assertion dropped or corrected, never weakened elsewhere)
Field/enum corrections: `justification_category` `CRITICAL_BUG_FIX`->`CRITICAL_BUG` and `MARKETING_DEADLINE`->`TIME_SENSITIVE_EVENT`; expedite decide field `rationale`->`decision_rationale`; `audience_released_pct`/`audience_held_pct`->`released_share_pct`/`held_back_share_pct`; `appeal_disposition is null`->`"PENDING"`; `assessed_by/filed_by == ${acct_id}`-> the acting operator's `X-User-ID`; PRD line 196's `ERR_INVALID_RULE_STATE`-> catalogue's `ERR_INVALID_GUIDELINE_STATE`; design pagination `limit == 20`-> PRD's 10; `reason_code PRIVACY_LABEL_MISMATCH`-> the published `PRIVACY_LABEL_INACCURATE`.

Unreachable-state sub-assertions dropped (recorded in each docstring where it mattered): the design's "final disclosure score == 0.8000 immediately after filing a finding" (the PRD pins `disclosure_accuracy_score_final` rewrites to claim + decision only, so the reachable routes are the late-`detected_at` and below-confidence-floor ones, both of which I used); `final == 0.6000` on the CRITICAL-finding freeze instance (a CRITICAL finding freezes the app before it can ever be claimed — asserted the uniquely-derived provisional `0.6000` plus the full `FROZEN`/`["CRITICAL_FINDING_OPEN"]`/index-100.00 posture instead); plus the previously recorded drops (`attested_by_user_id` after waive, `halt_distribution`/`rollback_reason_code`/`activated_at` echoes, `EXPIRING_SOON` status legs of the credential-deadline instances, the GAMBLING_SIMULATED dimension label, `commission_cents is null`, the `ReleaseManager`->`POST /feature-mappings` 403 leg, and four queue-error-code legs pre-empted by rung-7 `ERR_INVALID_SUBMISSION_STATE`).

**Orchestrator post-check:** `ls` confirms `test_helpers/` and `test_suite/` sit at the TASK ROOT, not under `workspace/` (a known failure mode of this step); `workspace/` contains only `INSTRUCTION.md`, `PRD.md`, `implementation/`, with no stray `test_*` or `conftest.py`. Independently re-ran `python3 -m pytest test_suite --collect-only -q` from the project root: **362 tests collected in 1.22s, 0 errors.**

## Step 7: Test and iterate loop — 2026-09-04T16:10:48.000Z

All 8 rounds are green. Final sweep: 362/362 in every round.

## Summary

**Iterations run:** 4 sweeps (103/362 → 343/362 → 360/362 → **362/362**). Zero flakiness observed in any iteration — every failure was deterministic across all 8 rounds.

**Tests deleted:** none. Every failure resolved either as a test/fixture faithfulness bug or a genuine implementation defect; no assertion was found to rest on a PRD-silent rule outright, and the three genuinely under-determined cases were handled with the sanctioned `validate_error_is_one_of` relaxation rather than deletion.

**Fixes applied to `test_helpers/`** (`/home/ubuntu/github/CodingPRD/tasks/task_2705_app_store_submission_review_compliance/test_helpers/fixtures.py`)
- `add_mapping` — register each mapping under both `key` and `feature_code` so `ctx.mappings[...]` lookups resolve for both callers.
- `setup_released_ios` — signature changed to `(client=None, mode="PHASED", scheduled_start_at=None, **kwargs)`; previously the positional client leaked into the rollout-plan payload as `mode`, producing `TypeError: Object of type ApiClient is not JSON serializable` in 4 tests.

**Fixes applied to `test_suite/`** (all paths under `.../test_suite/`)
- `test_02_difficulty_combinatorial_formula.py::test_understated_attestation_is_reported_then_blocks_queue_entry` — ERROR-PRECEDENCE SILENCE; relaxed to `validate_error_is_one_of([ERR_PRE_REVIEW_NOT_PASSED, ERR_INVALID_SUBMISSION_STATE])`, since the build is simultaneously not-attested and in `DRAFT` and PRD pins no ordering between the two rungs.
- `test_06_difficulty_boundary_precision.py::test_two_minor_findings_on_the_scope_boundaries_score_0_9000` — same relaxation, same reason.
- `test_12_corner_calculations.py::test_re_recording_the_same_questionnaire_voids_the_attestation` — same relaxation, same reason.
- `test_07_difficulty_cross_entity_state.py::_repass_mapping` — re-attestation now sends `PASS` directly; PRD line 200 declares `STALE → PASSED` under `PASS`, while `START` is declared only from `NOT_STARTED`. Fixed 2 tests' setup 409s.
- `test_11_corner_state_machines.py::test_remediating_an_overdue_assessment_is_the_only_write_allowed_while_frozen` — the frozen-posture probe now sends `FAIL` (a declared edge out of `PASSED`) so rung 7 passes and rung 8 is what answers.
- `test_14_corner_endpoints.py` — renamed to `test_filing_a_finding_rescores_the_provisional_and_leaves_the_final_null`; asserts `disclosure_accuracy_score_final is None`, because PRD line 242 rewrites the final score only at claim and at the decision gate and this build was never claimed.
- `test_15_corner_errors.py::test_four_critical_reasons_drop_the_account_below_the_expedite_floor` — setup re-PASSes the cascade-failed mapping so posture returns to `OPEN`, leaving standing as the sole obstacle the test is about.
- `test_16_corner_rbac.py::_setup_rejected_build_with_expedite` — same re-PASS, so `create_expedite_request` is not pre-empted by the restricted-posture gate.
- `test_17_corner_cross_cutting.py::test_the_lifetime_variant_never_moves_and_the_strike_row_survives` — per-instant expectation of `rejection_strike_count` = 1, 1, 1, **0**; PRD line 166 windows the strike count to the rolling 365 days (it is the lifetime *score* that never moves).

**Fixes applied to `workspace/implementation/`**
- `routes_submissions.py::void_attestation` — also clears `pre_review_checked_at` (PRD line 278 names all three fields).
- `routes_submissions.py::set_privacy_declaration` — no longer rewrites the *final* disclosure score; a declaration mutation moves the provisional only (PRD line 242).
- `routes_reviews.py::create_finding` — same: dropped the `IN_REVIEW` final-score recompute.
- `routes_reviews.py::decide_expedite` — removed an invented `ERR_INVALID_SUBMISSION_STATE` gate requiring the cited build to be `DRAFT`/`PRE_REVIEW_PASSED`. PRD §3.6 pins the complete refusal set for a grant and imposes no submission-state condition; §2.7 also requires the duty split to run before any business rule.
- `routes_guidelines.py::create_mapping` — `program_gate` now runs before `posture_gate`. Counting PRD line 126 shows "creating a feature mapping" is *not* among the sixteen frozen-blocked operations, so its "must not be frozen" rule sits in the business bands below rung 9.
- `routes_guidelines.py::self_review` — added the missing rung-8 posture gate; recording a self-review outcome *is* one of the sixteen.
- `routes_rollouts.py::rollback_plan` — a non-halting rollback now refuses with `ERR_INVALID_DISTRIBUTION_STATE` unless `distribution_state` is `PAUSED`; PRD line 188 declares `PAUSED → NOT_DISTRIBUTED` as the only non-halting edge. Left deliberately asymmetric (halting rollback stays reachable from `PHASE_ACTIVE`/`PAUSED`/`COMPLETED` per PRD line 298).

**Final per-round results:** results.1 362/362 · results.2 362/362 · results.3 362/362 · results.4 362/362 · results.5 362/362 · results.6 362/362 · results.7 362/362 · results.8 362/362.

**Orchestrator post-check (independent verification):** all 8 `results.$i.json` re-read directly — each `passed=362 total=362 failed=0 errors=0 skipped=0`, all 8 files written within the same 305s window (fresh, not stale from an earlier iteration). `grep -c Terminated workspace/sweep.log` → 0, confirming no round was reaped (the sweep ran under `setsid nohup` as mandated). Step 7 accepted.

## Step 8: Finalize PRD — align documentation to implementation — 2026-09-04T16:22:11.000Z

Done. `PRD_FINALIZED.md` is written.

## Line counts
- `PRD.md`: 484 lines · `PRD_FINALIZED.md`: 484 lines — **0.0% line delta** (6 lines revised in place, no lines added or removed, no new sections).

## Changes

- **§3.7 (age rating, PRD line 232)** — *insert* — defines what "voiding the attestation" means for a content mutation: `pre_review_passed` back to false and both `pre_review_checked_at` and `attested_by_user_id` cleared to null, unconditionally (so a `DRAFT` build that ran a failing self-review also loses its `pre_review_checked_at` stamp) — `implementation/routes_submissions.py:135-142`, called at `:306`.
- **§3.6 (metadata locale, PRD line 226)** — *insert* — attaching a locale also voids the attestation in that same three-field sense — `implementation/routes_submissions.py:751`.
- **§3.7 (privacy declaration, PRD line 234)** — *revise* — "voids a passed self-review" made explicit: drives `PRE_REVIEW_PASSED` back to `DRAFT` and voids in the same three-field sense — `implementation/routes_submissions.py:347`.
- **§3.4 (feature-mapping creation, PRD line 198)** — *insert* — names `ERR_APP_COMPLIANCE_FROZEN` and pins the order: account `program_status` first, then the app's frozen posture, then the cited rule's status; explicitly not a rung-8 rule because mapping creation is absent from §2.8's sixteen — `implementation/routes_guidelines.py:140-144`.
- **§3.8 (queue entry, PRD line 252)** — *insert* — the `PRE_REVIEW_PASSED → WAITING_FOR_REVIEW` transition is judged on rung 7 ahead of every content rule, so a `DRAFT` build reports `ERR_INVALID_SUBMISSION_STATE`, not `ERR_PRE_REVIEW_NOT_PASSED` — `implementation/routes_submissions.py:415-417` vs `:455-456`.
- **§3.10 (rollback, PRD line 298)** — *insert* — a non-halting rollback is refused `ERR_INVALID_DISTRIBUTION_STATE` unless `distribution_state` is already `PAUSED`; the halting flavour stays reachable from `PHASE_ACTIVE`/`PAUSED`/`COMPLETED` — `implementation/routes_rollouts.py:248-251`.

## Pre-edit search log

1. **Voiding the attestation (3 edits share one subject).** (a) Subject: which fields a content mutation clears, and the `PRE_REVIEW_PASSED → DRAFT` drive. (b) Grepped `void_attestation` across `implementation/` — defined `routes_submissions.py:135`, called from `set_age_rating:306`, `set_privacy_declaration:347`, `create_locale:751`; also read every other writer of the three fields: `pre_review_check:390-401` (sets `pre_review_checked_at` *before* scoring, stamps or clears `attested_by_user_id`), `return_to_draft:690-692` (clears all three), `create_submission:195-198` (initial nulls). (c) Adjustment: added "unconditionally" and the failing-self-review clarification so the sentence stays true on the `DRAFT`-state callsites, and deliberately said nothing about score recomputation — only the privacy-declaration path rewrites the provisional score (`:350`), age-rating does not, and §3.7/§3.9 already govern that.
2. **Feature-mapping creation gate order.** (a) Subject: relative position of the frozen-posture check for mapping creation. (b) Grepped `posture_gate|program_gate` across all route modules (30 hits): `routes_guidelines.py:140-141` is the *only* inverted pair; every other endpoint (`routes_submissions.py:169/388/420`, `routes_rollouts.py:52/126/171`, `routes_commerce.py:64/116`, `routes_apps.py:119`, `routes_reviews.py:441`) is posture-then-program. Also read `flows.posture_gate` to confirm `release_advancing=False` here, i.e. `FROZEN` only, and cross-checked §2.8's sixteen (mapping creation absent) and §2.9's fourteen (mapping creation present). (c) Adjustment: scoped the wording with "here" so it re-orders nothing globally, and kept §2.7's ladder text untouched.
3. **Queue-entry state precedence.** (a) Subject: rung-7 state check vs the `pre_review_passed` business rule at queue entry. (b) Read `queue_submission` end to end (`:406-489`) for the full rule order, plus `pre_review_check` and `void_attestation` to confirm `state == PRE_REVIEW_PASSED` always implies `pre_review_passed is True`. (c) Adjustment: phrased the `ERR_PRE_REVIEW_NOT_PASSED` clause as "can only answer once the state rung has already been satisfied" rather than declaring it dead, since the impl retains the check and the invariant is emergent, not asserted.
4. **Non-halting rollback.** (a) Subject: preconditions and edges of the two rollback flavours on `distribution_state`. (b) Grepped `distribution_state` across `implementation/` (16 hits) and read every writer: `routes_rollouts.py:142/148/191/217/222/263`, `flows.pause_active_plans:69-70`, `routes_apps.py:45` (init) and the readers `calc.py:504` (exposure factor), `routes_apps.py:132` (`LIST` gate), `routes_commerce.py:185` (revenue report). Confirmed the `PAUSED`-only rule exists solely at `routes_rollouts.py:248`, and that the cooldown at `create_plan:67-74` fires only for halting rollbacks. (c) Adjustment: described the halting flavour in terms of *plan* states (`PHASE_ACTIVE`/`PAUSED`/`COMPLETED`), matching the existing §3.10 sentence, instead of claiming a universal set of permitted `distribution_state` values — the pre-existing `ERR_APP_NOT_DISTRIBUTED` guard at `:241-244` would have made a stronger claim false.

Items in `<step_7_diff>` that needed **no** PRD edit, with the reason: both `test_helpers/fixtures.py` fixes (pure fixture bugs); `set_privacy_declaration` / `create_finding` dropping the final-score recompute and the `test_14` rename (PRD line 242 already pins final-score rewrite to claim and decision only, and `triage_finding:149` correctly rewrites both); `decide_expedite` (PRD line 262 + §2.10 already pin the complete refusal set with no submission-state condition); `self_review`'s added posture gate (PRD line 126 already lists it among the sixteen); `_repass_mapping` and the `FAIL` probe (PRD line 200 already declares `STALE → PASSED` under `PASS` and `START` only from `NOT_STARTED`); the `test_15`/`test_16` re-PASS setups (PRD line 126 already lists expedite creation as restricted-blocked); `rejection_strike_count` windowing (PRD line 166 already windows it, and `calc.standing_details:320-331` matches).

**Orchestrator post-check:** `PRD_FINALIZED.md` exists and is NOT byte-identical to `PRD.md` (121130 B → 122643 B, +1513 B over 6 revised lines), confirming the finalizer actually edited rather than only copying. Step 8 accepted.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-09-04T17:23:24.000Z

**Orchestrator decision (recorded per the AUTONOMY constraint):** Step 9 was run as **three sequential module-partitioned passes** over one shared `PRD_COMPLETED.md`, rather than as a single subagent. Rationale: a single agent asked to exhaustively scan 4329 lines of implementation across 14 files against a 484-line PRD reliably runs out of working room and produces a file byte-identical to its input (i.e. the scan never actually happens). Partitioning by implementation module keeps each pass's read set small enough to be walked exhaustively. Pass 1 performed the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden from copying, and each was handed the prior passes' "already uniquely pinned" list so they would not re-litigate settled prose, plus a no-false-universals rule (any wording reaching beyond the pass's own subset must be checked against the other modules and narrowed) and a respect-earlier-prose rule (narrow, never delete, a prior pass's sentence).

Partition:
- **Pass 1** — `app.py`, `common.py`, `valid.py`, `routes_accounts.py`, `routes_apps.py`, `start.sh` (1292 impl lines)
- **Pass 2** — `calc.py`, `flows.py`, `routes_submissions.py` (1645 impl lines)
- **Pass 3** — `routes_guidelines.py`, `routes_reviews.py`, `routes_rollouts.py`, `routes_commerce.py` (1381 impl lines)

### Pass 1 summary (verbatim)

Pass 1 complete.

## Copy confirmation
`cp workspace/PRD_FINALIZED.md workspace/PRD_COMPLETED.md` ran as the first action. `PRD_FINALIZED.md` and `PRD.md` untouched.

- PRD_FINALIZED.md: 484 lines / 122,643 chars
- PRD_COMPLETED.md: 484 lines / 130,181 chars
- char delta: **+7,493**; 20 distinct lines revised (lines 17, 21, 46, 76, 78, 82, 90, 114, 144, 160, 162, 164, 172, 174, 178, 180, 184, 186, 308, 399). No new sections or paragraphs — all in-paragraph inserts/revisions.

## Counts
- ambiguity-pins: **18**
- mismatch-revisions: **4**

## Changes
- §2.1 — insert — ambiguity — platform roles sending `X-Publisher-Account-Id` have it ignored, not rejected — `common.py:447-448`
- §2.1 — insert — ambiguity — a reference resolving to an unowned row (`GuidelineRule`, `ReviewCapacityWindow`) never trips tenancy; list narrowing precedes pagination so `total_count` counts only the narrowed set — `common.py:465-480,496-499,514-518,391-395`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 upper-case-alphanumeric chars — `common.py:309-313`
- §2.3 — insert — ambiguity — non-digit `limit`/`offset` text is `ERR_VALIDATION` 422, not ignored — `common.py:376-387`
- §2.3 — insert — ambiguity — `created_at` ties broken by insertion order — `common.py:182-184`
- §2.3 — insert — ambiguity — string filters are compared literally and never enum-validated (out-of-enum matches nothing); boolean filters accept `true/false/1/0` else 422 — `common.py:398-403,415-424`
- §2.4 — insert — ambiguity — only `created_at`/`updated_at`/`api_request_timestamp` always carry 3 fractional digits; domain instants and the echoed clock drop a zero fraction. Inbound instants accept 0–6 fractional digits and `Z` or numeric offset, normalised to UTC — `common.py:196-231`
- §2.5 — revise — mismatch — clock monotonicity: only a *strictly* earlier value is rejected; equal is accepted and re-runs the sweep — `routes_accounts.py:317-319`
- §2.7 — insert — ambiguity — a JSON boolean is never accepted for integer/number; a non-object body is rejected, but an absent/empty body reads as `{}` — `valid.py:69,95`, `common.py:521-527`
- §2.7 — insert — ambiguity — a non-string body reference skips the existence rung entirely and surfaces as 422, never 404 — `common.py:187-190,506-508`
- §2.11 — insert — ambiguity — scaled decimals are serialized as bare JSON numbers (`90.0`, `0.0`), not strings — `common.py:320-329`
- §3.1 — insert — ambiguity — explicit `null` `commerce_program_tier` is a schema violation (does not take the default); accounts filterable by `program_status`, `commerce_program_tier` — `routes_accounts.py:43-44,70-75`
- §3.1 — insert — ambiguity — renewal flips `program_status` only on `EXPIRED → ACTIVE`; `ACTIVE`/`SUSPENDED`/`TERMINATED` keep status and `enforcement_reason_code` — `routes_accounts.py:101-104`
- §3.1 — revise+insert — mismatch+ambiguity — `REINSTATE` boundary is "at or behind" the clock (equality yields `EXPIRED`); enforcement has no state precondition from any status; `reason_code` required on all three actions and validated-then-discarded on `REINSTATE` — `routes_accounts.py:115-127`
- §3.2 — insert — ambiguity — `linked_cert_id` resolving to a non-`DISTRIBUTION_CERT`, and a non-null one on a certificate, are both `ERR_VALIDATION`; both 409 checks sit after the 412 guard, and custody outranks platform mismatch — `routes_accounts.py:164-184`
- §3.2 — insert — ambiguity — activation ladder is credential state → program status (incl. `ERR_ACCOUNT_SUSPENDED`) → validity interval, so the 403 beats `ERR_CREDENTIAL_NOT_YET_VALID` — `routes_accounts.py:228-236`
- §3.2 — insert — ambiguity — compromise `reason_code` is non-empty but not persisted; `revocation_reason` stays null on the compromised credential — `routes_accounts.py:267-275`
- §3.2 — insert — ambiguity — exactly `ACTIVE` and `COMPROMISED` are revocable; `PENDING_ACTIVATION`/`EXPIRING_SOON`/`EXPIRED`/`REVOKED` are `ERR_INVALID_CREDENTIAL_STATE`; explicit null `revocation_reason` → `MANUAL` — `routes_accounts.py:286-299`
- §3.3 — insert — ambiguity — `bundle_id` is 1–200 chars, compared literally with no reverse-DNS parsing — `routes_apps.py:27`
- §3.3 — insert — ambiguity — the creation-time posture computation is not a mutation; the record returns with `version` 1 — `routes_apps.py:54` (`bump=False`)
- §3.3 — revise+insert — mismatch+ambiguity — `PlatformPolicyAdmin` on a non-`DELIST` action is `ERR_ROLE_NOT_PERMITTED` 403 raised *after* the `listing_action` schema check but before the listing-state check; all four actions pass the posture and program rungs; `METADATA_INCOMPLETE` vs `SCREENSHOT_SET_INCOMPLETE` is discriminated by whether any primary locale exists at all — `routes_apps.py:105-129`
- §3.3 — revise — mismatch — `LIST` requires `distribution_state` ∈ {`PHASED_ROLLOUT`, `FULLY_RELEASED`, `PAUSED`}, so `ROLLED_BACK` also fails with `ERR_APP_NOT_DISTRIBUTED`; `DELIST` is not precondition-free (posture/program gates apply, so a frozen app cannot be delisted) — `routes_apps.py:119,132-138`
- §3.11 — insert — ambiguity — `period_label` is a mandatory query parameter on the settlement read; missing or empty is 422 — `routes_apps.py:185-187`
- §5 — insert — ambiguity — unknown route and wrong method both return `ERR_VALIDATION` 422 in the standard envelope with no header check; trailing slashes are tolerated — `app.py:22,35-45`

## Already uniquely pinned in my subset (do not re-litigate)
- Header-shape rung: seven role names, account-backed trio requires `X-Publisher-Account-Id`, all shape failures are `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` 400 before role check (`common.py:430-459`).
- Role permission precedes lookup; tenancy precedes existence; two-pass `resolve()` (`common.py:483-511`).
- `id` as un-prefixed UUID, `created_at`/`updated_at` 3-digit ISO, `version` starts at 1 and +1 per mutation incl. cascades (`common.py:281-303`).
- Envelope shapes: `meta`/`response_type`/`data`; pagination keys only on list responses; error `meta` limited to two keys; `has_more` semantics; empty `data` object (`common.py:339-366`).
- `limit` default 10 / range 1–100, `offset` default 0 / non-negative (`common.py:372-388`).
- Full error-id → HTTP status table and the fifteen 404 codes (`common.py:48-148`).
- Account creation defaults: `ACTIVE` iff paid-through later than now, both standing scores 100.00, 2 credits, strike count 0, empty `settlement_finalized_periods`, null `enforcement_reason_code`; `legal_name` 1–120 unique as `ERR_VALIDATION`; `contact_email` must contain `@` (`routes_accounts.py:36-61`).
- Credential registration defaults (`PENDING_ACTIVATION`, nulls, `blocked_submission_count` 0), `entitlements` default `[]`, half-open validity with `not_after > not_before` as 422, account `version` bump, and the six list filters (`routes_accounts.py:144-213`).
- Activation supersession rule (same account + type + platform, `ACTIVE`/`EXPIRING_SOON` → `REVOKED`/`SUPERSEDED`) and the account-wide posture recompute (`routes_accounts.py:249-259`).
- Revocation reason enum {`SUPERSEDED`,`MANUAL`,`COMPROMISE_CASCADE`} and the `ERR_CREDENTIAL_IN_USE` in-review check (`routes_accounts.py:286-305`).
- Clock endpoint open to all seven roles; response carries exactly the echoed `current_utc` plus the six sweep counters (`routes_accounts.py:311-329`).
- App-record creation defaults and the two independent state dimensions; the seven list filters; `RETURN_TO_DRAFT` blocked by `SCHEDULED`/`PHASE_ACTIVE`/`PAUSED` plans as `ERR_INVALID_ROLLOUT_STATE`; listing actions never touch `distribution_state`, `live_submission_id` or the share fields (`routes_apps.py:38-70,140-146`).
- `compliance-summary` field set and its non-persisting, non-versioning nature (`routes_apps.py:149-178`).

### Pass 2 summary (verbatim)

Pass 2 complete.

## Size

- PRD_COMPLETED.md at entry: **484 lines / 130181 chars**
- PRD_COMPLETED.md at exit: **484 lines / 142844 chars** (+12663 chars; line count unchanged because every patch was an in-paragraph revision — the PRD's one-paragraph-per-topic prose style was preserved)
- 32 `Edit` calls, grouped into 18 substantive changes: **14 ambiguity-pins, 4 mismatch-revisions**

## Changes

- §2.4 — insert — ambiguity — a recomputation that lands on the value already stored writes nothing: no `updated_at` refresh, no `version` bump; enumerated exactly which recomputers are guarded (posture/index, account standing, window slot accounting, priority triple) so the rule is not over-claimed — `calc.py:158-170, 229-246, 390-400, 420-430`
- §2.5 — insert — ambiguity — sweep step (6) re-evaluates standing/expedite windows for **every** publisher account and then re-runs priority steps 2–6 for **every** `WAITING_FOR_REVIEW` submission, last of anything the sweep does — `flows.py:247-265`
- §2.5 — revise — ambiguity — an advance to the instant already stored reports all six counters at 0 and advances no row's `version` (was silent on repeat-advance behaviour) — `flows.py:189-267`
- §2.8 — revise — **mismatch** — narrowed a universal: posture/index are recomputed after a `REJECT` decision (via the rejection cascade) but **not** after `APPROVE` or `METADATA_REJECT`; appeal decisions do recompute. Prior prose said "after every submission decision" — narrowed rather than deleted, per the pass-1 respect rule — `routes_submissions.py:583-648`, cross-checked `routes_reviews.py:375-410`
- §2.10 — insert — ambiguity — must-differ vs must-equal asymmetry against a null recorded identifier: must-differ passes vacuously, must-equal always fails — `flows.py:34-43`
- §3.1 — insert — ambiguity — standing-summary diagnostics: which members are window-scoped vs lifetime, `credit_total` being the rolling figure, and integer-vs-2dp shapes — `calc.py:309-363`
- §3.2 — revise — **mismatch** — compromise cascade: an extra `version` bump on the credential per blocked build; posture recomputed for **every** app of the owning account (not only apps with blocked builds); hop 4 pauses only when the resulting posture is non-`OPEN`, and the app-row mirror fires only from `PHASED_ROLLOUT` — `flows.py:87-117`
- §3.2 — insert — ambiguity — the 168-hour warning boundary is inclusive — `flows.py:208-212`
- §3.2 — insert — ambiguity — only `ACTIVE`/`EXPIRING_SOON` credentials are in the sweep's reach; `PENDING_ACTIVATION` is left untouched past `not_after` (and is thereafter unactivatable), and no credential is counted twice — `flows.py:202-212`, activation guard `routes_accounts.py:234-237`
- §3.4 — insert — ambiguity — index is `0.00` when total weight is zero or no rows exist; a mapping whose rule reference dangles is excluded — `calc.py:102-116`
- §3.6 — insert — ambiguity — submission-creation field bounds/null handling and rung ordering (credential ladder ahead of the duplicate-build scan) — `routes_submissions.py:159-217`
- §3.6 — revise — **mismatch** — a `RESTRICTED` posture does **not** block submission creation (only `FROZEN` does); the prose had claimed it did, contradicting the §2.8 release-advancing split — `routes_submissions.py:169`, `flows.py:16-23`
- §3.6 — insert — ambiguity — creation auto-withdraws the app's other `DRAFT` submissions and refunds their expedites; locale bounds/defaults/editable states/`version` 1/nested-read filters — `routes_submissions.py:239-250, 705-753`
- §3.7 — insert — ambiguity — age-rating and privacy-declaration editable states; the `FLOOR_RULE` dimension label is decided from floor-vs-base before the gambling raise and before band snapping; privacy-item member shape; provisional score is `1.0000` when `pre_review_checked_at` is null; pre-review check is DRAFT-only, bodyless, emits only the eight pinned codes, and clears `attested_by_user_id` on failure — `calc.py:206-236, 252-281`; `routes_submissions.py:284-403`
- §3.7 — revise — **mismatch** — over-disclosure is charged **per declared tuple** outside the scoped set, not per distinct data type — `calc.py:195-200`
- §3.8 — insert — ambiguity — full queue-entry evaluation order including the metadata test and `ERR_REMEDIATION_INCOMPLETE`; window selector's insertion-order final tiebreak; the credential-deadline refusal is computed on a scratch copy so it writes nothing; a null provisional score contributes risk 0 — `routes_submissions.py:422-476`; `calc.py:453-455, 478-481`
- §3.9 — insert — ambiguity — rejection-reason entry shape and bounds; each `guideline_rule_id` resolves on the existence rung (404 before schema 422); `METADATA_REJECT` also requires `EFFECTIVE` rules; return-to-draft runs the full credential ladder; withdrawal `reason_code` is validated 1–80 then discarded — `routes_submissions.py:495-510, 541-570, 620-625, 671-686`
- §3.11 — insert — ambiguity — settlement response shape and per-line members, with each commission rate re-derived at read time — `calc.py:547-580`

## Subset behaviours judged already uniquely pinned (pass 3 need not re-litigate)

`posture_gate`'s FROZEN-vs-RESTRICTED code split and the release-advancing operation list; `program_gate`'s EXPIRED→403 / SUSPENDED+TERMINATED→`ERR_ACCOUNT_SUSPENDED` mapping; the guideline-publication cascade's mapping re-point, STALE marking, impact-assessment creation and `impacted_app_count`; the rejection cascade's PASSED→FAILED narrowing; sweep steps (1)–(5) ordering and their strict-vs-inclusive comparisons; the thirteen pinned calculations' formulas, quantizers and ROUND_HALF_UP; commission round-per-line-then-sum; the seven phase percentages; capacity-window slot arithmetic; all §3.6–§3.9 role lists and parent-revision guards.

## Confirmations

- No `cp` was run, and PRD_FINALIZED.md / PRD.md / implementation / test_suite / test_helpers were not modified. PRD_COMPLETED.md was the only file written, always via `Edit`.
- Pass 1's edits are still present (verified by spot-grep of pass-1-only markers, and by size: PRD_FINALIZED.md is 122643 chars, pass 1 left the file at 130181, pass 2 exits at 142844 — a pure monotone growth with no truncation).
- No server was started, no test suite was run, no pattern kill was issued.
- One pass-1 sentence contradicted my subset (§2.8's "after every submission decision") and was **narrowed, not deleted**, as noted in bullet 4 above.

### Pass 3 summary (verbatim)

Pass 3 complete.

## Counts

| | line count | char count |
|---|---|---|
| PRD_COMPLETED.md at entry | 484 | ~142,844 |
| PRD_COMPLETED.md at exit | 484 | 161,589 |

(`PRD_FINALIZED.md` remains 484 / 122,643, md5 `b4820ef…`; `PRD.md` md5 `9b61fbe…` — both untouched. No new sections were added, hence the unchanged line count: every patch is an in-paragraph insert or revision.)

**46 patches: 33 ambiguity-pins, 13 mismatch-revisions.**

## Changes

Pre-compaction (9):
- §2.1 — revise — mismatch — narrowed the blanket list-narrowing claim; guideline-rule and capacity-window lists are unscoped — `routes_guidelines.py:73`, `routes_reviews.py:575`
- §2.6 — revise — mismatch — removed the justification that plan creation cancels rival plans; it cancels nothing — `routes_rollouts.py:75-93`
- §2.7 — revise — mismatch — `overturned_rejection_reason_ids` is *not* resolved on the existence rung — `routes_reviews.py:349`
- §2.7 — revise — mismatch — "code of the entity named in the path" narrowed; a rejection-reason response reports `ERR_INVALID_SUBMISSION_STATE` — `routes_reviews.py:188-191`
- §3.4 — revise — mismatch — publish refusal is `ERR_INVALID_GUIDELINE_STATE`, not `ERR_INVALID_RULE_STATE` — `routes_guidelines.py:90`
- §3.4 — revise — mismatch — mapping creation is `ComplianceOfficer` only, and its rung order is program → posture → rule status — `routes_guidelines.py:115,140-144`
- §3.4 — insert — ambiguity — `requires_feature_mapping` takes its `true` default on explicit `null` too — `routes_guidelines.py:37`
- §3.4 — insert — ambiguity — evidence written whatever the outcome; `WAIVED_BY_PLATFORM` is terminal for self-review; every outcome bumps `version` — `routes_guidelines.py:191-215`
- §3.4 — insert — ambiguity — uniqueness breaches without a dedicated code land on `ERR_VALIDATION` — `routes_guidelines.py:38-42`

This session (37):
- §3.4 — insert — ambiguity — `waiver_reason` >500 is `ERR_VALIDATION` vs <20 `ERR_EVIDENCE_REQUIRED`; duty split → safety → length order; `attested_by_user_id` deliberately not re-stamped — `routes_guidelines.py:228-244`
- §3.4 — insert — ambiguity — `supersedes_rule_id` resolved on the existence rung before schema — `routes_guidelines.py:31`
- §3.4 — insert — ambiguity — publication bumps both the published and the superseded rule's `version` — `routes_guidelines.py:103-107`
- §3.5 — revise — ambiguity — both `ACCEPT_NO_CHANGE` gates share `ERR_IMPACT_TOO_SEVERE`, safety first — `routes_guidelines.py:305-310`
- §3.5 — insert — ambiguity — restored mappings clear `staled_by_rule_id` and bump `version`; non-`STALE` named mappings untouched — `routes_guidelines.py:312-316`
- §3.5 — insert — ambiguity — `note` 1-1000, null leaves prior narrative; every action bumps `version` and recomputes index+posture — `routes_guidelines.py:281,325-329`
- §3.5 — revise — mismatch — `MARK_REMEDIATED` is not the *only* frozen-permitted action; the whole `assess` endpoint has no posture rung — `routes_guidelines.py:274-330`
- §3.7 — insert — ambiguity — `endpoint_domain` 1-200, `scanner_confidence` quantized to 4dp — `routes_reviews.py:61-73`
- §3.7 — insert — ambiguity — filing rewrites only the provisional score and bumps the submission's `version` at any severity — `routes_reviews.py:82-87`
- §3.7 — insert — ambiguity — the triage role split is `ERR_ROLE_NOT_PERMITTED` after schema, before the state rung; `justification` overwritten unconditionally — `routes_reviews.py:118-124,146`
- §3.7 — revise — mismatch — the final score is also rewritten by any triage — `routes_reviews.py:38-41,149`
- §3.8 — insert — ambiguity — `reviewer_pool_code` 1-40; `ends_at <= starts_at` is `ERR_VALIDATION` — `routes_reviews.py:532-537`
- §3.8 — revise — mismatch — the new window counts its own `capacity_slots` into the ceiling, so a lone 11-slot window is refused — `routes_reviews.py:538-550`
- §3.8 — insert — ambiguity — close takes no body, re-closing is `ERR_REVIEW_WINDOW_CLOSED`, bumps `version` — `routes_reviews.py:586-595`
- §3.8 — insert — ambiguity — slot counters re-derived on every window read without bumping `version` — `routes_reviews.py:573-583`
- §3.8 — insert — ambiguity — expedite filing is release-advancing (posture + program rungs ahead of the standing floor, standing recomputed first); submission state unexamined — `routes_reviews.py:441-446`
- §3.8 — revise — mismatch — the expedite duty split applies to `DENY` too; quota precedes standing; both branches stamp `decided_by_user_id` — `routes_reviews.py:500-515`
- §3.9 — revise — mismatch — appeal filing order is already-open → state → window → contested, with the program rung ahead and no posture rung; cited ids unique and resolved on the existence rung — `routes_reviews.py:219-247`
- §3.9 — insert — ambiguity — board review takes no body and judges appeal state first; the decision's duty split follows the subset `ERR_VALIDATION` — `routes_reviews.py:289-300,351-367`
- §3.9 — insert — ambiguity — mapping restoration is by rule + currently-`FAILED`; the appeal approval supersedes but skips the `PHASE_ACTIVE` refusal and all four content gates — `routes_reviews.py:307-336`
- §3.9 — insert — ambiguity — `UPHELD` recomputes no posture; `overturned_…ids` ignored on the whole-appeal outcomes; every branch re-stamps `decided_at` — `routes_reviews.py:384-397`
- §3.9 — insert — ambiguity — withdrawal: `BOARD_REVIEW` refused, `reason_code` 1-80 discarded, submission returns only from `APPEAL_PENDING` — `routes_reviews.py:406-421`
- §3.9 — insert — ambiguity — `developer_response` mandatory 1-2000; state rung after schema; re-answerable; no posture/program rung — `routes_reviews.py:186-194`
- §3.10 — insert — ambiguity — plan creation checks neither the submission's state nor its ownership, cancels nothing, and runs guard → posture → program → mode → conflicts — `routes_rollouts.py:44-74`
- §3.10 — revise — mismatch — the 72h cooldown applies only to *halting* rollbacks with a `terminated_at` — `routes_rollouts.py:67-74`
- §3.10 — revise — mismatch — `ERR_ROLLOUT_NOT_DUE` is judged last, after state, submission, posture, program and exclusivity — `routes_rollouts.py:118-136`
- §3.10 — insert — ambiguity — start overwrites `distribution_state` unconditionally; an immediate plan recomputes standing at once — `routes_rollouts.py:142-156`
- §3.10 — insert — ambiguity — advance also carries the program rung; sequence precedes dwell — `routes_rollouts.py:171-182`
- §3.10 — insert — ambiguity — every advance bumps the app's `version`; only index 6 recomputes standing — `routes_rollouts.py:192-196`
- §3.10 — insert — ambiguity — hold has no program rung, overwrites `distribution_state`, `pause_reason_code` ≤80 cleared on `RESUME` — `routes_rollouts.py:207-222`
- §3.10 — insert — ambiguity — rollback rungs: plan state, then `ERR_APP_NOT_DISTRIBUTED`, then the non-halting edge rule — `routes_rollouts.py:236-251`
- §3.11 — insert — ambiguity — `reference_name` 1-120, `external_link_url` 1-500, `subscriber_retention_months` rejects explicit `null` — `routes_commerce.py:41-47`
- §3.11 — insert — ambiguity — creation order shape → name collision (all statuses) → `FROZEN`-only posture → program → digital-content; no entitlement check at creation — `routes_commerce.py:48-70`
- §3.11 — insert — ambiguity — submission re-derives the stored shape reporting `ERR_VALIDATION`; the entitlement scan ignores `platform` and excludes `EXPIRING_SOON` — `routes_commerce.py:20-28,112-136`
- §3.11 — insert — ambiguity — `rejection_note` ≤1000 stored only on reject; the duty split precedes both branches; commerce review has no posture/program rung — `routes_commerce.py:143-169`
- §3.11 — insert — ambiguity — `ERR_INVALID_COMMERCE_ITEM_STATE` then `ERR_APP_NOT_DISTRIBUTED` (three distributing states); no posture/program rung — `routes_commerce.py:181-187`
- §3.11 — insert — ambiguity — a report bumps the item's and the account's `version`; the period lock is account-wide across apps — `routes_commerce.py:189-200`

## Earlier-pass sentences I narrowed rather than deleted

Six, all flagged above and all narrowed in place with the surrounding prose kept: §2.1 (list narrowing), §2.6 (plan-creation justification), §2.7 ×2 (overturned-ids existence rung; path-entity code rule), §3.5 (the "only publisher action while frozen" claim), §3.7 (the final-score rewrite enumeration). I deliberately left §2.8's "after every mutation of a behaviour finding" posture claim alone: the implementation recomputes only for `CRITICAL` findings, but a non-critical finding can never move the posture, so the divergence is unobservable.

## Confirmations

`cp` was **never** run; `PRD_COMPLETED.md` was edited in place with 46 `Edit` calls and grew monotonically from ~142.8 KB to 161.6 KB. Passes 1 and 2's prose is intact and verified present (the §2.7 ladder, `resolve()` semantics, the error-status table, §2.8's tier computation and exempt list, §2.9's fourteen-operation list, §2.11's rounding-order rules, §3.9's standing definition all still read as they did). No server was started, no test run, no pattern kill issued, no file other than `PRD_COMPLETED.md` written. §4's role table was cross-checked against all four of my modules and matches exactly, so no table row needed changing.

Every endpoint, transition, ordering rule, field bound, default, side effect and error code in `routes_guidelines.py`, `routes_reviews.py`, `routes_rollouts.py` and `routes_commerce.py` now traces to a PRD sentence, with no residual ambiguity or mismatch known to me in my subset.

### Orchestrator post-check (independent verification)

- `workspace/PRD_COMPLETED.md` exists: 484 lines / **161,589 bytes**, grown from `PRD_FINALIZED.md`'s 122,643 B — **+38,946 B (+31.8%)** across **68 revised lines** (136 diff lines). NOT byte-identical to its input, so the scan genuinely ran (the known failure mode where a single overloaded Step 9 agent copies and never edits).
- Structure intact and not truncated: 5 top-level sections in order (§1 Introduction line 3, §2 Global Specifications line 11, §3 Business Logic line 156, §4 API Endpoint Specifications line 310, §5 Error Handling line 397); the §4 table still carries 82 rows (80 endpoints + header + separator) and the §5 table still carries 81 `ERR_*` rows, both identical in count to `PRD_FINALIZED.md`; the file ends on a complete final table row (`| ERR_REVENUE_ALREADY_REPORTED | 409 |`), a real section boundary.
- Line count deliberately unchanged at 484 across all three passes — every patch was an in-paragraph insert or revision, no new sections or paragraphs, as the skill requires.
- No implementation or test file was modified by Steps 8 or 9: newest `.py` mtime across `workspace/implementation/`, `test_suite/` and `test_helpers/` is 15:53:59 UTC, earlier than the green sweep's `results.1.json` at 16:05:11 UTC. The 8-round 362/362 result therefore still describes the code as it stands.
- Step 9 accepted. **Pipeline complete.**
