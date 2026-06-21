# Worklog — task_0280_cable_satellite_tv_subscription

## Step 1: Create task directory — 2026-06-10T00:00:00.000Z

Created `tasks/task_0280_cable_satellite_tv_subscription/` with `workspace/` subdirectory. Index 0280 is pre-assigned/reserved (no re-scan of ./tasks/). Difficulty: Expert.

## Step 2: Generate scaffold — 2026-06-10T00:00:00.000Z

Generated three scaffold artifacts for **task_0280_cable_satellite_tv_subscription** at **Expert** difficulty. All files pass `scaffold_lint.py` (VERDICT: clean lint; 52 endpoints, 13 entities, 357 §1.8/§1.9 calls verified).

**Complexity profile:** pricing_engine (primary) + event_sourcing (secondary); layers dual_variant_calculation, cascading_side_effects, rate_threshold_triggers, derived_field_reconciliation, optimistic_concurrency; hybrid topology, parallel state-machine shape, peer_roles, immediate consistency.

**Entities (13):** 5 catalog/config (ChannelPackage, PremiumChannel, EquipmentModel, PromotionOffer, RegionalSportsFeeRule, Technician — 6 actually) plus aggregate root Account and its children Subscription, AddOnSubscription, EquipmentLease, ServiceVisit, PromotionApplication, BillingStatement.

**State machines (5):** Account.lifecycle_status (linear w/ suspend cycle + cancel), Account.promo_status (cyclic NONE→PROMO_ACTIVE→ROLLED_BACK→PROMO_ACTIVE win-back), Subscription.status (supersede/downgrade), ServiceVisit.status (branching fork-join DISPATCHED→{COMPLETED,NO_SHOW}, plus CANCELLED), EquipmentLease.status (ASSIGNED→RETURNED|UNRETURNED).

**Counts:** 6 calculations (monthly_recurring_charge, promo_discount, regional_sports_fee, visit_fee, statement_total [FULL_CYCLE vs PRORATED dual-variant], early_termination_fee), 20 validations, 52 endpoints (incl. reverse-lookup lists + `/_clock` test-driving endpoint), 21 errors, 4 roles (BillingAdmin/CustomerServiceAgent opaque; FieldTechnician entity_backed:Technician; Subscriber entity_backed:Account), 2 concurrency rules (OCC on Account.version for tier-change and win-back).

**Difficulty design (§1.8):** 9 rule_ids × 2 = **18 instances**. **Corner design (§1.9):** 8 sections, **43 instances** (39 active test recipes + 4 `excluded_because` stubs). `api_prefix` set to `""` (multi-root REST surface).

Files: SCAFFOLD.yaml (964 lines), SCAFFOLD_DIFFICULTY_DESIGN.yaml (940 lines), SCAFFOLD_CORNER_DESIGN.yaml (1359 lines).

## Step 3: Copy shared files — 2026-06-10T00:00:00.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-10T00:00:00.000Z

Generated `workspace/PRD.md` (~348 lines, 52105 bytes). Both design files (SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml) withheld; no sibling tasks referenced.

**Structure:** 5 top-level sections, 23 subsections.
- §1 Introduction; §2 Global Specifications (12 subsections: RBAC w/ 4 roles + identity translations; fixed §2.2 envelope; pagination; common properties incl. no-`updated_at`/no-`version` carve-out for Technician & RegionalSportsFeeRule; cascade semantics; nested-path existence ordering; validation precedence; account-active gate; OCC; monetary precision; enum catalogue; test-driving clock); §3 Business Logic (11 subsections); §4 endpoint table (52 rows); §5 error table (21 rows).

**Hard Contracts — all PASS:** Field coverage 70/70; Rule coverage (20 validations w/ precedence, 2 OCC rules, 5 state machines, 6 calculations w/ full formulas + constants, 21 error IDs, sibling-branch symmetry); Path purity (§3: 403 backtick tokens scanned, 0 path/method violations).

## Step 5: Generate unit tests — 2026-06-10T00:00:00.000Z

Generated complete test infrastructure, translating purely from the two design indices + PRD.

**test_helpers/ (9 files):** types.py (Technician & RegionalSportsFeeRule omit version/updated_at per §2.4), api_client.py (one method per §4 endpoint), api_errors.py (21-error enum + HTTP map), assertions.py, factories.py, constants.py, test_users.py (opaque CSA/BillingAdmin + make_field_technician_headers/make_subscriber_headers builders), fixtures.py, __init__.py.

**test_suite/ (conftest + 8 files, 72 tests):**
- test_01_pricing_and_statements.py (12), test_02_state_machines_and_cascades.py (8), test_03_validation_precedence_and_constraints.py (6), test_04_visits_and_boundaries.py (8), test_05_entities_crud.py (9), test_06_state_transitions.py (9), test_07_calculations_and_validations.py (12), test_08_endpoints_rbac_concurrency.py (8).

**Coverage:** Queue A (Difficulty) 17/18 instances ×2 = 34 tests (1 skipped). Queue B (Corner) 38/39 non-stub ×1 = 38 tests (1 skipped). 4 excluded_because stubs correctly NOT translated.

**Skipped (PRD-silence gaps):**
1. Difficulty/priority_pair_validation_conflict/visit_window_safety_beats_temporal_overlap — PRD §3.9 lists three visit guards as a set w/ no precedence ordering; not uniquely derivable.
2. Corner/entities/create_account_missing_required_field_returns_invalid_request — ERR_INVALID_REQUEST only in §5 table, no prose trigger; §2.11 names ERR_VALIDATION as body-validation fallback; not uniquely derivable.

**Audits passed:** every docstring ends with exactly one Design: tag (all 72 resolve); all 72 PRD citations verbatim-match; no skip/xfail markers; all imports resolve.

## Step 6: Generate implementation — 2026-06-10T00:00:00.000Z

Built complete Python + Flask implementation in workspace/implementation/.

**Source files:** app.py (Flask entry, blueprint reg, error handlers, binds 0.0.0.0:$PORT), db.py (in-memory dicts keyed by UUID; new_id/stamp_new/touch), errors.py (ApiError + 21 IDs/statuses), response.py (exact envelope, req_ id, ISO-8601 ms, pagination meta), clock.py (wall clock + settable test-driving clock), middleware.py (X-User-ID/X-User-Role extraction, 4-role validation/authz), services/calculations.py (6 calcs, Decimal round-half-up, per-line prorated rounding), services/accounts.py (recompute + lifecycle + cascades), services/common.py (body parse, pagination, catalog lookup, ownership-before-existence resolver), routes/ (catalog, lookups, accounts, subscriptions, addons, equipment, visits, promotions, billing), start.sh, requirements.txt.

**Storage:** purely in-memory module-global dicts; nothing seeded/preloaded/hardcoded; fresh boot = empty store. start.sh guards pip install on `import flask` check, then `exec python3 app.py` foreground reading $PORT (default 10000) on 0.0.0.0.

**Coverage confirmed:** 52 endpoints (url_map=52 routes), 6 calculations, 5 state machines w/ cascades, 21 errors. Smoke tests pass. Deliberate PRD-fidelity point: per §2.7 resource-ownership precedes account-existence (Subscriber on missing account → ERR_NOT_RESOURCE_OWNER before ERR_ACCOUNT_NOT_FOUND).

## Step 7: Test & iterate loop — 2026-06-10T00:00:00.000Z

Clean exit after a green 8-round parallel sweep.

**Iterations run:** 2 (initial sweep surfaced 4 stable failures — all failed in all 8 rounds, no flakiness; second sweep after fixes was 71/71 clean across all 8 rounds).

**Initial state:** 68/72 in every round. Four failures, each stable across all 8 rounds.

### Tests deleted (1)

- **`test_cancel_cycle_statement_combines_prorated_recurring_and_one_time`** (`test_07_calculations_and_validations.py`) — DELETE per STEP 1b, **DEFAULT-VALUE / COMPUTED-FIELD silence** at the PRD-prose level. The test asserts the cancellation-cycle statement bills the package at prorated 3000. But PRD §3.7 *explicitly defines* "the account's single current subscription" as "the one in `ACTIVE` or `DOWNGRADED` status," and §3.10 sources the package amount from "the current subscription's `base_fee_cents`." After the §3.3 cancellation cascade transitions the subscription to `TERMINATED`, no ACTIVE/DOWNGRADED subscription remains, so a PRD-faithful implementer yields `package_charge_cents == 0`. The PRD prose admits both the 0 and 3000 readings (I can articulate both PRD-faithful implementations), so it does not uniquely determine the outcome. Scaffold rule that drove it: `Corner/calculations/cancel_cycle_statement_combines_prorated_recurring_and_one_time_etf` (the scaffold *intended* 3000, but the PRD prose failed to encode that uniquely).

### Fixes applied to test_suite/ (3 fixtures — all STEP 2 test bugs, made more faithful to PRD)

- **`test_technician_zero_gap_adjacent_window_allowed`** (`test_04_visits_and_boundaries.py`) — fixture scheduled both visits on the **same account** with a 0-minute gap, which correctly tripped the PRD §3.9 account-level 60-minute-buffer rule (`ERR_ACCOUNT_VISIT_CONFLICT`), masking the technician half-open adjacency rule the test intends to verify. Changed to two distinct accounts (same technician), matching the pattern already used by the passing technician-overlap tests, so the technician rule is exercised in isolation → 201 as the cited PRD sentence requires.

- **`test_technician_back_to_back_before_existing_allowed`** (`test_04_visits_and_boundaries.py`) — same root cause and same two-distinct-accounts fix.

- **`test_downgrade_with_stale_version_rejected`** (`test_08_endpoints_rbac_concurrency.py`) — the second tier change targeted a subscription left in `DOWNGRADED` status by the first downgrade, which is not a legal source state, so the higher-precedence state check (`ERR_INVALID_STATE`, PRD §2.7) fired before the OCC guard could. Changed the first tier change to an **upgrade** (PRD §3.4: an upgrade leaves the new row `ACTIVE`), so the second tier change's target is in a legal source state and the stale `expected_account_version` correctly reaches the OCC check → `ERR_STALE_ACCOUNT_VERSION`.

### Fixes applied to implementation/ (none)

The implementation was faithful to the PRD in all four cases — the account-buffer rule, the cancellation cascade terminating the subscription, and the §2.7 state-before-concurrency precedence were all correct. No implementation code was changed.

**Final state:** 71/71 passing in all 8 parallel rounds, zero failures, zero errors.

## Step 8: Finalize PRD — 2026-06-10T00:00:00.000Z

Produced `workspace/PRD_FINALIZED.md` — minimal patch over PRD.md. Line counts: 348 → 348, one line revised (0 added/removed), ≈0.29% delta.

**Change:**
- **§3.10 (statement shared inputs)** — *revise* — pinned the statement's "package amount" to the §3.7 definition of the single current subscription (`ACTIVE`/`DOWNGRADED`), and made explicit that it is 0 (so `package_charge_cents` is 0) when no such subscription exists — notably on the cancellation-cycle statement after the §3.3 cascade has set the subscription to `TERMINATED`. — `implementation/services/calculations.py:191-192`.

**Why only one edit (per HARD SCOPE):** 3 of 4 step_7_diff items are pure fixture bugs whose behavior PRD already determines (§3.9 half-open adjacency; §2.7 state-before-concurrency + §3.4 upgrade leaves row ACTIVE). The one genuine PRD-silence is the deleted cancel-cycle-statement test: §3.10 did not restate §3.7's ACTIVE/DOWNGRADED qualifier nor the 0-fallback; impl yields 0.

**Pre-edit search (§3.10):** grepped `current_subscription|base_fee_cents|package_charge|package =`; confirmed consistency at calculations.py:36-41 (current_subscription filters ACTIVE/DOWNGRADED), :131-132 (recurring `if sub else 0`), :191-192 (statement `if sub else 0`), :211-227 (FULL/PRORATED both 0 when package 0), promotions.py:81-82 (promo snapshot same), accounts.py:61 (cancel cascade). Wording chosen as general no-current-subscription fallback (not cancellation-only) to stay consistent with every path.

## Step 9: Complete PRD — 2026-06-10T00:00:00.000Z

Produced `workspace/PRD_COMPLETED.md` — minimal patch over PRD_FINALIZED.md via full impl scan. Source 348 lines / 52,460 chars → 349 lines / 55,840 chars (char-delta +3,375). No new sections; one in-list bullet added; rest in-paragraph.

**Counts:** 9 ambiguity-pins, 0 mismatch-revisions.

**Per change:**
- §2.3 Pagination — insert — ambiguity — `limit` clamps to [1,100], negative `offset` clamps to 0, non-integer limit/offset → ERR_VALIDATION — common.py:67-88
- §2.3 Pagination — insert — ambiguity — list ordering ties on created_at broken by ascending id — common.py:94
- §2.7 Validation Order — insert — ambiguity — body referenced-id presence/type (→ERR_INVALID_REQUEST) before catalog/sub-resource existence; expected_account_version validated at concurrency step — subscriptions.py:71-93, promotions.py:22-34
- §2.11 Enumerations — insert — ambiguity — ERR_INVALID_REQUEST (missing/null/wrong-type required field, malformed JSON) vs ERR_VALIDATION (well-typed but disallowed enum / out-of-range/negative) — common.py:28-61, errors.py:109-122
- §2.12 Test-Driving Clock — insert — ambiguity — current_utc re-serialized ISO 8601 (3 fractional digits); pre-set fallback is real wall-clock UTC — clock.py:37-41, visits.py:24-34
- §3.3 Cancellation — insert — ambiguity — cancel cascade leaves promo_status and any (even ACTIVE) PromotionApplication untouched — accounts.py:50-86
- §3.9 Service Visits — insert — ambiguity — no-show takes no body, leaves outcome_note null; completed/no-showed visit fee attributed to account tenure_months at terminal transition — visits.py:166-186, calculations.py:177-185
- §3.10 Cycle Advancement — insert — ambiguity — advance-cycle not lifecycle-gated; permitted in any lifecycle_status, never ERR_ACCOUNT_NOT_ACTIVE — accounts.py:92-98, accounts.py:89
- §3.10 Statement Issuance — insert — ambiguity — days_in_cycle ≥ 28 / active_days ≥ 0 validated in either mode (below-bound → ERR_INVALID_REQUEST); 0..days_in_cycle range rule is PRORATED-only — billing.py:25-31
- §3.11 Reverse-Lookup Reads — insert — ambiguity — single-resource flat get on missing id → ERR_SUBRESOURCE_NOT_FOUND, except GET /channel-packages/{id} → ERR_CATALOG_ENTITY_NOT_FOUND; missing account-scoped statement → ERR_SUBRESOURCE_NOT_FOUND — lookups.py:34-141, catalog.py:71-78, billing.py:86-94

## Pipeline complete — 2026-06-10T00:00:00.000Z

Orchestrator independently re-ran the final 8-round parallel stability sweep (the Step-7 results files had been cleaned up). **All 8 rounds: passed=71 failed=0 total=71.** Durable per-round evidence regenerated at `workspace/implementation/results.{1..8}.json`. Task complete.
