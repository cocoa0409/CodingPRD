# Worklog — task_2618_gift_card_fraud_balance_protection

## Step 1: Create task directory — 2026-09-03T20:20:34.661Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2618_gift_card_fraud_balance_protection` and `workspace/` (pre-assigned path; no index allocation performed).

## Step 2: Generate scaffold — 2026-09-03T21:49:58.407Z

All three scaffold artifacts for task 2618 are complete and verified.

**Output directory:** `/home/ubuntu/github/CodingPRD/tasks/task_2618_gift_card_fraud_balance_protection/`

## SCAFFOLD.yaml (4264 lines, 209841 bytes)
`domain_name: gift-card-fraud-balance-protection`, `api_prefix: "/"`, no `scaffold_difficulty_design` / `scaffold_corner_design` keys present.

| §1.1 entities | §1.2 state machines | §1.2.1 concurrency rules | §1.3 calculations | §1.4 validations | §1.5 endpoints | §1.6 errors | §1.7 roles |
|---|---|---|---|---|---|---|---|
| 14 | 11 | 2 | 14 | 42 | 62 | 41 | 7 |

Complexity profile: layers `[rate_threshold_triggers, cascading_side_effects, dual_variant_calculation, optimistic_concurrency]`, topology `flat`, shape `parallel`, role model `segregation_of_duties`, consistency `immediate`.

## SCAFFOLD_DIFFICULTY_DESIGN.yaml (1454 lines, 93244 bytes)
Single top-level key `scaffold_difficulty_design`. 9 rule ids × 2 instances = **18 instances**: `dual_variant_calc` 2, `combinatorial_formula` 2, `non_linear_state_machine` 2, `transitive_cascade` 2, `priority_pair_validation_conflict` 2, `boundary_precision_check` 2, `cross_entity_state_dependency` 2, `resource_temporal_overlap` 2, `compensating_invariant` 2.

## SCAFFOLD_CORNER_DESIGN.yaml (4432 lines, 284573 bytes)
Single top-level key `scaffold_corner_design`. All nine claim-extraction-guide sections, **94 instances** (79 with `test_recipe`, 15 `excluded_because` stubs):

| section | instances | recipes | stubs |
|---|---|---|---|
| entities | 13 | 13 | 0 |
| state_machines | 17 | 13 | 4 |
| calculations | 13 | 10 | 3 |
| validations | 15 | 10 | 5 |
| endpoints | 8 | 7 | 1 |
| errors | 12 | 12 | 0 |
| rbac | 8 | 8 | 0 |
| cross_cutting_complexity_layers | 7 | 5 | 2 |
| consistency_model | 1 | 1 | 0 |

## Verification
- `scaffold_lint.py` → `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (757 calls scanned across 18 + 79 recipe-bearing instances).
- Independent resolver pass: 0 unresolved `grounds` (all resolve into §1.1–§1.7, including `state_machines.<Entity>.<dimension>` and `response_envelope.pagination_defaults`); 0 duplicate `name`s across the union of both design files (112 unique); 0 stubs carrying a `test_recipe`; all 15 `excluded_because.difficulty_instance` citations resolve to real §1.8 names; 0 unbound `${var}` references; all 41 §1.6 error codes triggered or stub-attributed.

Bugs caught and fixed during this pass: `LedgerEvent` has no `reversed_by_event_id` field (assert rewritten to use the `reverses_event_id` filter); a rack audit of 4-of-6 was asserted TAMPERED when `rack_shrink_threshold` 3 makes it SUSPECT (changed to 3-of-6); pagination envelope fields (`total_count`, `has_more`) cannot be captured from array-output endpoints under lint rule (d), so those six captures became prose asserts; a `grounds` path used `api_conventions.` instead of `response_envelope.`.

## Step 3: Copy shared files — 2026-09-03T21:49:58.407Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T22:06:08.376Z

PRD generation is complete and verified.

**Output:** `workspace/PRD.md` — **483 lines**, written in nine chunked `cat >>` appends (no single giant Write). The document ends at a real boundary: the final row of the §5 error table (`| ERR_REISSUE_LIMIT_EXCEEDED | 422 |`), with no audit footer or trailing prose.

**Section list**
- §1. Introduction
- §2. Global Specifications & System-Wide Principles — 2.1 Identity, Roles and Access Control; 2.2 API Response Structure (verbatim fixed block); 2.3 Pagination; 2.4 Resource Identity, Timestamps and the Logical Clock; 2.5 The Risk Policy Register; 2.6 Money, Basis Points, Scores and Rounding; 2.7 Stale-Version Guards on Additive Writes; 2.8 Request Validation Order (13-tier ladder covering all 42 rules); 2.9 Derived Fields, Cascades and Deterministic Ordering; 2.10 Path Resolution and Reverse Lookups
- §3. Business Logic & Workflows — 3.1 Retail Floor Monitoring: Racks, Audits and the Tamper Cascade; 3.2 Stocking, Activation Controls and Digital Issuance Screening; 3.3 Bulk Purchase Monitoring and Identity Capture; 3.4 The Card Ledger: Redemption, Reversal and Balance Projection; 3.5 Redemption Holds and Aggregate Interval Capacity; 3.6 Card-Draining Detection: Inquiry Velocity, Drain Scoring and Posture; 3.7 Alert Investigation, the Confirmation Cascade and Law-Enforcement Referral; 3.8 Secondary-Marketplace Listings and Card Validation; 3.9 Victim Claims, the Evidence Cycle and Card Reissue; 3.10 Balance-Liability Accounting and Unauthorized-Redemption Reserves
- §4. API Endpoints (4-column table, 62 rows)
- §5. Error Codes (2-column table, 41 rows)

**Coverage (documented / scaffold total)**
- Endpoints: **62 / 62** — verified programmatically against the scaffold: identical order, no missing/extra method+path pairs, all 62 role sets exactly matching.
- Errors: **41 / 41** in §5, and all 41 also named in the §1–§3 prose.
- Calculations: **14 / 14**.
- State machines: **11 / 11**, all 67 transitions expressed.
- Roles: **7 / 7**.
- Validations: 42 / 42 in the §2.8 ordered ladder; both OCC rules named with endpoint + `expected_gift_card_version` / `expected_liability_period_version` + error id.

**Contract reports**: Field coverage PASS (153/153 entity fields, 112/112 endpoint payload fields). Rule coverage PASS (42 validations, 2 OCC, 67 transitions, 14 calcs incl. all 4 variant pairs, 62 endpoint side-effect sets, 14 entities reconstructible, 8/8 sibling-branch symmetry groups equal density). Path purity PASS (911 backtick tokens scanned in §3, 0 paths/methods leaked).

**Three scaffold-internal contradictions** resolved by editorial decision and applied consistently: (1) `missing_evidence_kinds` enum — used the priority-25 enforceable set `PURCHASE_RECEIPT`/`PACKAGING_PHOTO` over the entity-field set; (2) rack-tamper hop 3 scope — used the store-scoped card selection over the rack-scoped wording in the audits endpoint; (3) `screening_components` keys — used the calculation's explicit six-key set `device`/`email`/`payment`/`amount`/`base`/`bulk_surcharge`. Neither withheld design file was opened; no sibling task directory read.

**Orchestrator truncation check**: `tail -25` ends on the last error-table row; `grep '^## '` shows all five top-level sections present. Not truncated — accepted without regeneration.

## Step 5: Generate unit tests — 2026-09-03T23:05:32.315Z

Test suite generation for `task_2618_gift_card_fraud_balance_protection` is complete and verified.

## Output paths (confirmed)
Both directories are at the TASK ROOT; `ls -la workspace/` shows only `INSTRUCTION.md`, `PRD.md`, `implementation/` — **no `test_helpers/` or `test_suite/` under `workspace/`**, and nothing under `workspace/implementation/` was read or written.

## Files and line counts

test_helpers/ (2908 lines): `__init__.py` 243, `api_client.py` 327 (62 endpoint methods), `api_errors.py` 119 (41 `ERR_*` + `ERROR_HTTP_STATUS` installed at import), `assertions.py` 491 (every PRD formula re-derived), `constants.py` 150, `factories.py` 442, `fixtures.py` 773 (5 tiers of world-builders), `test_users.py` 100, `types.py` 263.

test_suite/ (9390 lines): `conftest.py` 17; queue A `test_01` 230, `test_02` 218, `test_03` 204, `test_04` 262, `test_05` 175, `test_06` 190, `test_07` 199, `test_08` 174, `test_09` 252; queue B `test_10_corner_entities` 683, `test_11_corner_state_machines` 1212, `test_12_corner_calculations` 1016, `test_13_corner_validations` 1088, `test_14_corner_endpoints` 836, `test_15_corner_errors` 703, `test_16_corner_rbac` 1055, `test_17_corner_cross_cutting` 719, `test_18_corner_consistency_model` 157.

## Tests per queue — 254 total
- **Queue A (difficulty): 60 tests** covering **18/18** non-stub instances.
- **Queue B (corner): 194 tests** covering **79/79** recipe-bearing instances — entities 21, state_machines 39, calculations 23, validations 24, endpoints 22, errors 21, rbac 25, cross_cutting 15, consistency_model 4.

AST audit: 254 tests, 254 `Design:` lines, exactly one per test and always the last docstring line; 97 unique tags; **0 untagged, 0 dual-tagged, 0 duplicate test names**. Diff against both yamls keyed by real section/rule: **missing 0, invalid 0, and none of the 15 `excluded_because` stubs was translated**.

## Verification
- `python3 -m py_compile` on all 9 helper + 19 suite files: **PY_COMPILE ALL OK**.
- `python3 -m pyflakes` on all 28 files: **CLEAN** (no unused imports, no undefined names).
- **Import-resolution check** (importing all 18 test modules with `PYTHONPATH` set as the runner does): 0 failures. This caught a real collection-time bug py_compile cannot see — `test_05` imported `ERR_CARD_FROZEN`/`ERR_IDENTITY_VERIFICATION_REQUIRED` from the package root, which does not re-export error ids (`ImportError`); repointed to `test_helpers.api_errors`. Also expanded the truncated `__all__` in `test_helpers/__init__.py` to all 114 re-exports and dropped an unused re-export in `conftest.py`. `__pycache__` removed.
- No pytest run, no server started, no process killed.

## Instances skipped: none. Asserts dropped/adapted (PRD-first filter)
Design asserts the PRD does not uniquely derive were dropped outright (no weakening, no skip/xfail): `activated_at`/`decided_by_user_id` null-at-creation, initial `info_request_count`, initial `remediation_note`, `validation_note` readback, initial `drain_risk_score_inquiry`, `settled_at` (not a PRD field), `basis_drain_score == 60` on an auto-raised alert, `unauthorized_line_count` on denial, triage `triage_note`/`redemption_pattern_reviewed` echo, a vacuous 750x20 fee assert, and row-ordering asserts where rows share the frozen `created_at` (replaced with set membership plus `total_count`).

Six design-vs-PRD conflicts resolved the PRD's way: a client-supplied derived balance is **ignored, not rejected** (201 + zeroed fields); referral `exposure_snapshot_cents` is 10000 (`current_balance` + `total_redeemed`), not the yaml's 6000; `captured_amount_cents` is 0, not null; DIGITAL requests omit `store_id`/`rack_id`/`card_id` (so the storeless `declined_issuance_count` assert is unreachable); `DRIVERS_LICENSE` spelling; and the drain-score listing instance had to be split into two tests because validating both listings after lowering the threshold makes the yaml's expected `VALIDATED` unreachable. All timestamps are compared via `parse_instant`/prefix, never against a raw literal, because the PRD mandates three fractional digits.

## Step 6: Generate implementation — 2026-09-03T23:05:32.315Z

The implementation is complete, verified, and the smoke server is shut down.

## Files (all under `workspace/implementation/`)

| File | Lines |
|---|---|
| `start.sh` (executable, guarded pip, `exec python3 app.py`) | 8 |
| `requirements.txt` (`flask>=2.0`) | 1 |
| `app.py` (blueprints + ApiError/404/405/500 envelope handlers, `0.0.0.0:$PORT`) | 70 |
| `clock.py` / `db.py` / `errors.py` / `response.py` / `middleware.py` / `validate.py` | 59 / 137 / 113 / 70 / 72 / 162 |
| `routes/`: common 111, config 63, stores 150, gift_cards 286, issuance 245, bulk 136, alerts 179, claims 273, listings 83, liability 131, ledger 60 | 1717 |
| `services/`: money 41, cards 184, stores 88, scoring 92, holds 51, listings 34, bulk 26, liability 75, claims 37, alerts 54 | 682 |
| **Total Python** | **3082** |

## Coverage vs. spec

- **Endpoints: 62 / 62.** Flask URL map diffed against every `- method:/path:` pair in `SCAFFOLD.yaml`: `ROUTES_MATCH`, zero extras, zero missing.
- **Errors: 41 / 41.** Every scaffold `error_id` exists in `errors.py`, every one is actually raised somewhere in `routes/`, `services/`, `middleware.py` or `validate.py`, and all 41 `http_status` values match the catalog exactly (programmatic diff, 0 mismatches). No invented codes.
- **Calculations: 14 / 14** — balance projection (`cards.recompute`), inquiry velocity, both drain-score variants, digital screening, bulk order total, claim reissue, both reserve variants, alert exposure snapshot, rack classification, floor posture, hold capacity, period overlap, listing decision, net-funded-liability invariant. All money/score/ratio work uses `Decimal` + `ROUND_HALF_UP` (per-line-then-sum for reissue, once-over-aggregate for reserves, post-rounding +15 digital surcharge).
- **State machines: 11 / 11** — GiftCard `activation_state`, GiftCard `risk_posture` (parallel dimensions), CardRack, RetailStore floor, IssuanceRequest, RedemptionHold, BulkPurchaseOrder, DrainingAlert, VictimClaim, ResellerListing, LiabilityPeriod.
- **Validations: 42**, wired as a 13-tier first-violation-wins ladder (auth -> role -> StoreManager scope -> well-formedness -> existence in the PRD's declared order -> OCC -> card guards -> transition legality -> safety/SoD -> referential -> window -> quantitative -> fiscal).
- Storage is in-memory dicts only; nothing is seeded at boot except the singleton risk-policy register (PRD 2.5 configuration, not an entity).

## Smoke test (`PORT=39217`, killed by exact PID 2415354 found via `ss -ltnp` on that port only — no pattern kill)

Booted in <4 s. Exercised end-to-end: `GET /risk-policy` (200, defaults, logical clock at `2026-08-01T00:00:00.000Z`) - `POST /stores` (201) - `GET /stores?limit=5` (200, `response_type: array`, `total_count: 1`, `has_more: false`) - `POST /card-racks` (201) - `POST /gift-cards` (201, INACTIVE/CLEAR, generated masked PAN) - `POST /issuance-requests` + `/screen` (auto-APPROVED on an OPEN floor, card -> ACTIVE 10000, `rack_id` cleared) - `/decide` on the already-approved request -> `ERR_INVALID_ISSUANCE_STATE` - `POST /redemptions` (201, `signed_amount_cents: -4000`) - `POST /balance-inquiries` (score 29 = 12*1+30*0.40+5*1) - alert raise/triage/resolve CONFIRM (score 38 = 45*0.40+14*1+6*1, exposure 10000 = balance+redeemed, card -> FROZEN, VALIDATED listing -> BLOCKED/`CARD_RISK_POSTURE`) - referral file + reverse-lookup list (immutable shape: no `version`/`updated_at`) - ledger reverse (201) then repeat -> `ERR_LEDGER_EVENT_ALREADY_REVERSED` - hold with wrong version -> `ERR_STALE_CARD_VERSION`, correct version on a frozen card -> `ERR_CARD_FROZEN` - listing duplicate -> `ERR_DUPLICATE_LISTING` - bulk order (100000 subtotal -> 225 bps -> 2250 fee -> 102250 total, PENDING_IDENTITY -> IDENTITY_VERIFIED -> APPROVED) - claim intake, SoD violation -> `ERR_SEGREGATION_OF_DUTIES`, APPROVE 4-hop cascade (replacement minted ACTIVE with the 10000 residual, original CLOSED with `closed_at`), rescind restoring both cards - liability period create, overlap -> `ERR_PERIOD_OVERLAP`, close (gross 10000, basis 1, provisional 3500), stale restate -> `ERR_STALE_PERIOD_VERSION`, valid restate (final 1000, provisional preserved) - `exposure-summary` net funded liability conserved at 10000 across approve->rescind - clock move (`to_iso8601` -> `current_utc`/`expired_hold_count`) - rack audit -> TAMPERED, store -> SUSPENDED - envelope failures: no header 401, unknown role 403, unknown path 404 `ERR_NOT_FOUND`, bad method 405, bad id 404 `ERR_CARD_NOT_FOUND`.

Note: `PUT /risk-policy` cross-field guard (`drain_watch` >= `drain_restrict`) correctly returns `ERR_INVALID_REQUEST`. `__pycache__` was removed so the delivered tree is clean.

**Orchestrator location check**: `test_helpers/` and `test_suite/` confirmed at task root; `workspace/` contains only INSTRUCTION.md, PRD.md, implementation/ (0 test dirs). No relocation needed.

## Step 7: Run tests and iterate — 2026-09-03T23:37:08.981Z

Clean sweep achieved. Exiting.

## Summary

**Iterations run: 2** (sweep 1 -> diagnose/fix -> sweep 2 clean).

### Sweep 1 (baseline)
All 8 rounds identical: **251/256**, 5 failures, zero variance — fully deterministic, no flakiness and no reaping artifacts (`setsid` wrapper used throughout). Union of failures across all 8 rounds was exactly 5 tests, all sharing one root cause:

- `test_13_corner_validations.py::TestBulkIdentityGate::test_the_identical_approval_succeeds_once_the_identity_is_on_file`
- `test_14_corner_endpoints.py::TestBulkRequestInfoReturnsTheOrderToPending::test_request_info_reverses_the_identity_step_and_counts_the_round_trip`
- `test_14_corner_endpoints.py::TestBulkRequestInfoReturnsTheOrderToPending::test_the_cleared_hash_makes_the_next_approval_fail_until_a_new_id_lands`
- `test_14_corner_endpoints.py::TestBulkRequestInfoReturnsTheOrderToPending::test_the_loop_leaves_the_money_frozen_and_never_clears_the_counter`
- `test_15_corner_errors.py::TestIdentityCaptureOnAnAlreadyVerifiedOrder::test_capturing_identity_on_that_order_is_invalid_bulk_order_state`

All five failed with `400 ERR_INVALID_REQUEST — Field 'id_expiry_date' is not a valid ISO-8601 UTC instant`, thrown from `POST /bulk-purchase-orders/{id}/identity-verification`. This matched the triage hint (>=5 failures, one shared upstream cause).

### Tests deleted: none
No test failed STEP 1a (coverage) or STEP 1b (unique derivability). PRD 3.3 verbatim covers every asserted rule (identity capture fields, the `REQUEST_INFO` clearing of all three identity fields, `info_request_count` increment, money fields frozen at creation, `ERR_INVALID_BULK_ORDER_STATE` on capture against a non-`PENDING_IDENTITY` order).

### Fixes applied to `test_helpers/`: none
The fixture was audited first per the triage hint and found **faithful**. `test_helpers/factories.py::identity_payload` supplies `id_expiry_date: "2030-01-01"`, and the test-suite call sites supply date-only literals (`"2030-04-30"`, `"2031-01-31"`, `"2029-06-30"`). PRD 3.3 requires only `id_expiry_date`, "the document's expiry", persisted verbatim as `identity_id_expiry_date` — it declares **no format** for the field. 2.4 enumerates every field read from the logical clock (`created_at`, `updated_at`, `occurred_at`, `activated_at`, `closed_at`, `screened_at`, `last_audit_at`, `referred_at`, `restated_at`) and this client-supplied field is not among them; it is also the only `_date`-suffixed field in the whole spec, every genuine instant being `_at` / `_start` / `_end` / `to_iso8601`. So 2.8 tier 4's "every datetime parses as ISO 8601 UTC" does not verbatim reach it, and a date-only expiry is a PRD-valid payload. No test anywhere asserts a malformed `id_expiry_date` is rejected.

### Fixes applied to `implementation/` (1 fix)
- **`workspace/implementation/routes/bulk.py`, `verify_identity()`** — swapped `validate.datetime_field(body, "id_expiry_date")` for `validate.string(body, "id_expiry_date", min_len=1)`. The strict ISO-8601-instant check was an implementation-invented constraint with no verbatim PRD sentence behind it; it also coerced the value to a `datetime`, defeating PRD 3.3's verbatim-persistence requirement ("Those land on the order as ... `identity_id_expiry_date`, the document's expiry"). The field remains required and non-null per 2.8 tier 4, and validation still precedes order existence (tier 4 before tier 5), so the state-conflict test now correctly reaches tier 8 and gets `409 ERR_INVALID_BULK_ORDER_STATE`.

No PRD-required check was removed or weakened, no assertion was downgraded, no `skip`/`xfail` exists anywhere in the suite (verified: 0 matches), and storage remains in-memory dicts only.

### Final clean sweep — per-round results (all 8 files on disk at `workspace/implementation/results.{1..8}.json`, written 23:27)

| Round | Passed | Total | Failed | Errors | Skipped |
|---|---|---|---|---|---|
| 1 | 256 | 256 | 0 | 0 | 0 |
| 2 | 256 | 256 | 0 | 0 | 0 |
| 3 | 256 | 256 | 0 | 0 | 0 |
| 4 | 256 | 256 | 0 | 0 | 0 |
| 5 | 256 | 256 | 0 | 0 | 0 |
| 6 | 256 | 256 | 0 | 0 | 0 |
| 7 | 256 | 256 | 0 | 0 | 0 |
| 8 | 256 | 256 | 0 | 0 | 0 |

8/8 rounds at `passed == total == 256`, zero skipped. Note the suite collects **256** tests, not the 254 stated in the task prompt.

**Orchestrator independent verification**: re-read all 8 `results.$i.json` from disk (each ~82.8 KB, mtime 23:27) — every round `passed=256 total=256 failed=0 errors=0 skipped=0`. `grep -c pytest.mark skip|xfail` over `test_suite/` returns 0. Sweep artifacts confirmed present and genuine; no re-run needed.

## Step 8: Finalize PRD — 2026-09-03T23:39:00.000Z

PRD_FINALIZED.md is in place at `workspace/PRD_FINALIZED.md`.

## Line counts
- PRD.md: 483 lines / 110,230 bytes
- PRD_FINALIZED.md: 483 lines / 110,944 bytes
- Line delta: 0 lines (0.00%); byte delta: +714 (+0.65%). Both edits are in-paragraph insertions, so no line count moves.

## Changes (2)
- 2.8 tier 4 — insert — added a sentence naming the six client-supplied datetime inputs (`hold_start`, `hold_expires_at`, `period_start`, `period_end`, `purchased_at`, `to_iso8601`) and explicitly excluding the bulk-order `id_expiry_date` from the "every datetime parses as ISO 8601 UTC" clause, stating it is checked only as a required non-empty string so a bare calendar date is well-formed — `implementation/routes/bulk.py:91`, cross-checked against `implementation/validate.py:89-98`.
- 3.3 (identity capture) — insert — pinned `id_expiry_date` as an opaque, required, non-null, never-parsed / never-reformatted / never-length-capped string that is stored and echoed back verbatim — `implementation/routes/bulk.py:91,97`.

Nothing else was patched. The Step 7 diff contained exactly one implementation fix, no test deletions and no fixture fixes, so there was no other PRD-silence site to close.

## Pre-edit search log

Edit 1 (2.8 tier 4)
- (a) Subject: which request fields the tier-4 ladder treats as datetimes vs. plain strings.
- (b) Enumerated: `grep -rn "datetime_field\|clock.parse" implementation/` -> the complete set of datetime-parsed client inputs is `routes/liability.py:24-25` (`period_start`, `period_end`), `routes/config.py:54` (`to_iso8601`), `routes/claims.py:32` (`purchased_at`), `routes/gift_cards.py:172-173` (`hold_start`, `hold_expires_at`), plus the helper `validate.py:89`. Then swept the inverse direction — `grep` of every `validate.string|integer|boolean|enum|string_list|absent` call across all 11 route modules filtered for `_at|date|time|iso` — to confirm no other temporal-looking field is accepted as a bare string anywhere (`id_expiry_date` at `routes/bulk.py:91` is the sole one). Also read `implementation/response.py:27-33` to confirm `serialize` reformats only real `datetime` objects, so a string field round-trips untouched.
- (c) Adjustment: initially considered "the datetime-typed inputs are exactly ..."; kept the enumeration but scoped it to *client-supplied* inputs so it cannot be misread as covering the server-stamped clock fields of 2.4 (`created_at`, `occurred_at`, `referred_at`, ...), which are minted, not validated. Also said "checked only as a required non-empty string" rather than "no validation" because `min_len=1` does reject `""`.

Edit 2 (3.3 identity capture)
- (a) Subject: `id_expiry_date` / `identity_id_expiry_date` — its validation, persistence and lifecycle.
- (b) Enumerated: `grep -rn "expiry_date"` over the whole workspace -> `routes/bulk.py:53` (initialised to `None` at order creation, both the `PENDING_IDENTITY` and the sub-threshold `IDENTITY_VERIFIED` branch), `:91` (validated), `:97` (assigned), `:135` (cleared to `None` on the `REQUEST_INFO` branch of `decide_order`). Confirmed no other module reads or writes the field, that `services/bulk.py`'s pricing path never touches it, and that `response.serialize` passes it through unchanged. Auxiliary evidence: `test_suite/test_13_corner_validations.py:267` asserts the stored value equals the literal `"2030-04-30"`, and `test_helpers/types.py:160` types it `Optional[str]`.
- (c) Adjustment: wrote "stored on the order and echoed back in responses exactly as supplied" rather than "immutable" or "persisted permanently", because `decide_order`'s `REQUEST_INFO` branch (`routes/bulk.py:135`) does clear it to empty — a stronger claim would have contradicted the clearing rule the very next paragraph states. Added "or length-capped" since `validate.string` is called with no `max_len`, and avoided saying the value "must look like a date" since nothing in the impl checks that.

## Step 9: Complete PRD — 2026-09-03T23:55:25.658Z

Both read cleanly. Work is complete and verified.

**Files:** `PRD_FINALIZED.md` 483 lines / 110,944 chars -> `PRD_COMPLETED.md` 483 lines / 121,581 chars (**+10,637 chars**, same line count — every change is an in-paragraph revision; no new sections, no new paragraphs).

**Counts:** 37 edits total — **28 ambiguity-pins**, **9 mismatch-revisions**. Pass A: 15 (12 pins / 3 mismatches). Pass B: 13 (8 / 5). Pass C: 9 (8 / 1).

### Pass A — infra + core cards
- 2.1 — revise — ambiguity — missing/empty/unknown `X-User-Role` -> `ERR_UNAUTHORIZED` 403; both headers trimmed — `middleware.py:37-42`
- 2.1 — revise — mismatch — store scoping bites only on single-target ops + a card's reverse lists; top-level lists never narrowed; store-less resources never scoped; body-store creation denies with `ERR_UNAUTHORIZED` — `middleware.py:46-72`
- 2.2 — revise — ambiguity — `api_request_id` = `req_` + 20 uppercase-alnum; `api_request_timestamp` read from the logical clock — `response.py:13-21`
- 2.4 — revise — ambiguity — clock response carries exactly `current_utc`/`expired_hold_count`; sweep runs on any move >= current reading, only strictly-backwards skips — `routes/config.py:56-63`
- 2.5 — revise — ambiguity — null key = omitted, unknown key ignored, ordering constraints checked on the merged register, no-op update still bumps `version` — `routes/config.py:28-46`
- 2.8 t5 — revise — mismatch — no endpoint accepts `reverses_event_id`; referral-not-found reports `ERR_ALERT_NOT_FOUND` — `routes/common.py:89-93`, `routes/ledger.py:39-48`
- 3.1 — revise — ambiguity — duplicate `rack_label` -> `ERR_INVALID_REQUEST` — `routes/stores.py:70-72`
- 3.1 — revise — ambiguity — new rack's `remediation_note` empty — `routes/stores.py:82`
- 3.1 — revise — mismatch — remediation has no tamper-state precondition (works on `INTACT`); note any length; `last_audit_at` untouched — `routes/stores.py:134-150`
- 3.2 — revise — ambiguity — duplicate client-supplied masked PAN -> `ERR_INVALID_REQUEST`; generated one retries — `routes/gift_cards.py:41-46`
- 3.4 — revise — ambiguity — redemption 201 body is the ledger event, not the card — `routes/gift_cards.py:164`
- 3.4 — revise — ambiguity — reversal returns the new event; `reversal_reason` any length; merchant/terminal empty — `routes/ledger.py:42-55`
- 3.4 — revise — mismatch — `amount_cents` >= 1 only where client-supplied (zero-value reissue credit excepted) — `services/cards.py:80-96`
- 3.5 — revise — ambiguity — hold 201 body is the hold; `settle_note` initially empty — `routes/gift_cards.py:190-203`
- 3.5 — revise — ambiguity — settle's `merchant_store_id` existence-checked ahead of the hold; capture without it still succeeds — `routes/gift_cards.py:252-279`
- 3.5 — revise — ambiguity — capture never re-tested against balance/capacity; 200 body is the hold — `routes/gift_cards.py:260-286`
- 3.6 — revise — ambiguity — override has no precondition, `reason` unstored, 200 body is the card — `routes/gift_cards.py:227-238`

### Pass B — risk + issuance
- 3.2 — revise — mismatch — at open, `card_id` is existence-only (not `INACTIVE`, not rack-membership); digital `pos_terminal_id` optional, `packaging_seal_intact` accepted-and-unused; null counts as omitted — `routes/issuance.py:74-113`
- 3.2 — revise — ambiguity — new request also has `review_note`/`decided_by_user_id` empty — `routes/issuance.py:132-133`
- 3.2 — revise — mismatch — a non-`INACTIVE` card does **not** refuse screening; request still reaches `APPROVED` with funding silently skipped — `routes/issuance.py:42-43`
- 3.2 — revise — ambiguity — held-physical `WATCH` escalation is monotone; no version bump when already >= WATCH — `routes/issuance.py:202-205`
- 3.2 — revise — mismatch — manual decide admitted from `SUBMITTED` too, never re-checks the seal, same silent funding skip, `decision` limited to APPROVE/DECLINE — `routes/issuance.py:218-238`
- 3.3 — revise — ambiguity — `REQUEST_INFO` records `decision_note` but not `decided_by_user_id` — `routes/bulk.py:131-138`
- 3.6 — revise — ambiguity — inquiry 201 body is the inquiry row with its seven fields — `routes/gift_cards.py:87-117`
- 3.7 — revise — ambiguity — manual alert's full empty-field set + `note` any length — `services/alerts.py:19-34`
- 3.7 — revise — mismatch — `redemption_pattern_reviewed` accepts `false` and still triages; `triage_note` any length — `routes/alerts.py:61-80`
- 3.7 — revise — ambiguity — triage can also lift `CLEAR`->`WATCH`; card version always bumps — `routes/alerts.py:74-75`
- 3.7 — revise — ambiguity — `resolution` stores the verb `CONFIRM`/`DISMISS`; card version moves on a no-op dismissal — `routes/alerts.py:100-117`
- 3.7 — revise — ambiguity — `reopen_reason` required but persisted nowhere — `routes/alerts.py:126`
- 3.8 — revise — ambiguity — listing created with `validation_note`/`validated_by_user_id` empty; both recorded on every verdict — `routes/listings.py:40-81`

### Pass C — claims + liability
- 2.10 — revise — ambiguity — exact filter parameter name per collection; unknown params ignored; nonexistent FK filter -> empty page — all `routes/*.py` list handlers
- 3.9 — revise — ambiguity — future `purchased_at` accepted (one-sided window test) — `routes/claims.py:44`
- 3.9 — revise — ambiguity — `unauthorized_line_count` 0 while the three cents figures are null at intake — `routes/claims.py:60-63`
- 3.9 — revise — mismatch — `missing_evidence_kinds` may be empty/repeating and replaces; resubmission with neither reference is accepted — `routes/claims.py:98-128`
- 3.9 — revise — ambiguity — empty-string reference counts as missing at the evidence gate — `routes/claims.py:159-163`
- 3.9 — revise — ambiguity — replacement card's `face_value_cents` 0, fresh masked PAN, `CLEAR`, `activated_at` stamped; credit appended even for 0 — `routes/claims.py:183-190`
- 3.9 — revise — ambiguity — original returns to `ACTIVE` unconditionally, depletion edge not re-applied — `routes/claims.py:256-258`
- 3.9 — revise — ambiguity — writeoff decrement unfloored/skippable; rescind retains all frozen figures plus decision fields — `routes/claims.py:262-271`
- 3.10 — revise — ambiguity — duplicate `label` -> `ERR_INVALID_REQUEST`, tested before occupancy — `routes/liability.py:28-32`
- 3.10 — revise — ambiguity — restatement leaves `closed_at`/`close_note` alone — `routes/liability.py:100-107`
- 3.10 — revise — ambiguity — exposure summary is exactly nine keys, echoing stored figures verbatim — `routes/liability.py:121-131`

### Final verification (verbatim)
```
$ diff $TASK_DIR/workspace/PRD_FINALIZED.md $TASK_DIR/workspace/PRD_COMPLETED.md | wc -l
150
```
37 changed hunks, all `NNNcNNN` single-line in-place replacements.

**Orchestrator verification**: PRD_COMPLETED.md is 483 lines / 121,581 chars, 37 diff hunks vs PRD_FINALIZED.md — not byte-identical, so the scan genuinely ran. `find workspace/implementation -name '*.py' -newermt '2026-09-03 23:28'` returns nothing: Step 9 did not touch the implementation, so the verified 8/8 x 256/256 sweep at 23:27 still holds for the delivered tree.

## Pipeline complete — 2026-09-03T23:55:25.658Z

All nine steps finished. Deliverables: SCAFFOLD.yaml + both design indices, workspace/PRD.md, workspace/PRD_FINALIZED.md, workspace/PRD_COMPLETED.md, test_helpers/ (9 files, 2908 lines), test_suite/ (19 files, 9390 lines, 256 tests), workspace/implementation/ (3082 lines Python, 62 endpoints), results.{1..8}.json all 256/256.
