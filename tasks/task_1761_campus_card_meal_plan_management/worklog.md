# Worklog — task_1761_campus_card_meal_plan_management

Difficulty directive from operator: **harder than expert level**.

## Step 1: Create Task Directory — 2026-08-14T14:11:51.000Z

Pre-assigned by pipeline runner; `tasks/task_1761_campus_card_meal_plan_management/workspace/` verified present. Step treated as DONE per instructions.

## Step 3: Copy Shared Files — 2026-08-14T14:12:20.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1761_campus_card_meal_plan_management/workspace/INSTRUCTION.md` (1424 bytes). Done out of order while Step 2 subagent runs (no dependency).

## Step 2: Generate Scaffold — 2026-08-14T15:33:01.000Z

All three artifacts are complete and lint-clean. The `worklog.md`/`workspace/` entries in the task directory were pre-existing harness files; I wrote only the three scaffold files.

## Summary

**Output files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1761_campus_card_meal_plan_management/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 + preamble only (verified: no design keys present)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`

**Counts:**
- Entities: **17** (incl. 2 self-referential FKs: `CampusCard.replaced_by_card_id`, `MealPlanEnrollment.supersedes_enrollment_id`, plus `MerchantSettlement.carried_from_settlement_id`; 2 append-only immutable entities: LedgerEntry, AccessEvent)
- State machines: **15** (parallel lifecycle × photo dimensions on CampusCard; cyclic settlement resubmission; branching disputes/change-requests; guarded grants; posture-gating Term)
- Calculations: **12** (3 dual-variant, all formula literals precomputed with Python)
- Validations: **14** priority tiers (auth → ownership → shape → existence → idempotency → state → OCC → cross-entity state → safety/SoD → temporal → constraint → fiscal)
- Endpoints: **92** (all 34 FK fields reverse-reachable per lint check f)
- Errors: **51** codes, every one triggerable by a §1.8/§1.9 instance
- Roles: **10** (2 entity-backed: CardHolder, MerchantUser; segregation-of-duties model with 4 SoD error codes across refund/settlement/dispute chains)
- §1.8 instances: **20** (all 9 rules ≥2; combinatorial_formula has 3 covering modes a/b/c; compensating_invariant has 3)
- §1.9 instances: **88** (79 active recipes + 9 excluded_because stubs; all 108 instance names unique across both files)

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (987 calls scanned)

**Harder-than-expert escalations applied:**
- **Archetype blend**: ledger reconciliation × temporal windowing, graph topology, 4 complexity layers (OCC, cascading side effects, scheduled/deferred actions, derived-field reconciliation)
- **3 OCC race surfaces** (enrollment change-request vs swipe mutation, account adjustment vs funding, card replacement vs photo review) — all OCC-on-version, zero forbidden race vocabulary (grep-verified)
- **Two depth-4 transitive cascades** from different triggers (report-stolen → strikes → suspension → account freezes/card deactivations/grant revocations; term-close → enrollment close → account CLOSE_PENDING → threshold forfeiture)
- **Dual-variant calcs in 3 distinct domains** (enrollment proration WEEKLY/DAILY, settlement commission PER_TRANSACTION/AGGREGATE, refund AUTO_EXCLUDING_PROVISIONAL/FULL_BALANCE); pinned rounding order with 1-cent-divergence proofs (81 vs 82 on identical inputs)
- **Mode-c evaluation-order pinning** in plan-change proration (old_earned → credit → new_due → delta), with deferred execution that can VOID on insufficient funds at advance-week
- **Boundary precision on 4+ metrics** (money equality, deadline-second inclusivity, strict swipe less-than, inclusive provisional daily cap, inclusive strike threshold)
- **Interval-semantics contrast**: half-open grant validity (adjacency allowed) vs closed-closed settlement periods (touching days conflict) vs half-open minute windows in door schedules
- **RBAC × ownership × state intersections**: entity-backed ownership filtering, SoD chains (adjuster≠approver≠payer; granter≠resolver; submitter≠approver), provisional-card restriction intersecting door access and daily spend caps, door denials modeled as data (6 deny_reasons) rather than errors
- All fixture dates driven by the declared `/_clock/set_current_utc` with the mandatory `2026-08-01T00:00:00Z` default.

## Step 4: Generate PRD — 2026-08-14T15:51:06.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_1761_campus_card_meal_plan_management/workspace/PRD.md`.

## Summary

**PRD line count:** 451 lines

**Section list:**
- 1. Introduction (3 paragraphs)
- 2. Global Specifications & System-Wide Principles — 2.1 RBAC · 2.2 API Response Structure (emitted verbatim, byte-identical to the canonical source) · 2.3 Pagination · 2.4 Common Resource Properties · 2.5 The Logical Clock · 2.6 Monetary Representation and Rounding · 2.7 The Ledger as the System of Record · 2.8 Idempotency · 2.9 Optimistic Concurrency Control · 2.10 Validation Priority Order · 2.11 Nested Resource Retrieval · 2.12 Mutation Semantics
- 3. Business Logic & Workflows — 9 subsections (registration/issuance/photo · loss-theft-replacement-fraud · terms & plan catalogue · enrollment/activation pricing/plan changes · accounts/funding/purchases/swipes · disputes & provisional credit · term closeout/refunds/forfeiture · door access · merchant program & settlement)
- 4. Endpoint Definitions — 92 rows (4 columns: Method, Path, Description, Authorized Roles)
- 5. Error Code Catalogue — 51 rows (2 columns: Error ID, HTTP Status)

## Coverage self-audit

Scaffold tables verified fully represented (programmatically checked against the scaffold YAML):

- **Contract 1 (Field-Name Coverage):** entities[].fields + endpoint input/query/output identifiers — 127 required, 127 present, 0 missing. PASS
- **Contract 3 (§3 Path Purity):** 905 backticked tokens scanned in §3; 0 path tokens, 0 bare HTTP methods, 0 method+path combos. PASS
- **Contract 2 (Rule Coverage):**
  - validations[] priority: 14 priorities expressed as an explicit ordered list in §2.10, each paired with its error IDs and statuses — 0 missing
  - concurrency_rules[]: 3/3 expressed with write capability + `expected_enrollment_version` / `expected_account_version` / `expected_card_version` + `ERR_STALE_VERSION` (412) — 0 missing
  - state_machines[].transitions: all 15 machines walked — every from/to pair (incl. the 4 replacement and 4 deactivate from-states, both EXPIRED lazy paths, REJECTED→PENDING_REVIEW unbounded photo cycle), every precondition paired with its error_id, every side effect (suspension/stolen/withdraw/graduate/term-close cascades, grant revocation chains) expressed — 0 missing
  - calculations[]: 12/12 in precise prose with pinned evaluation orders — activation pricing (both variants, charge-then-grant, zero-grant rule), plan-change 5-step proration, tiered replacement fee (5 ordered rules, ordinal-consumed note), settlement sweep (both rounding variants), refund waterfall (both variants + residue), cancellation credit (floor at 0), swipe reset (strict less-than), provisional cap (2500, inclusive), fraud escalation (threshold 3, inclusive), ledger recompute (direction map, replay order, both invariants), dispute carryover (period override + invariant), access decision selector (7 pinned steps)
  - validations[] conditions: all 51 error IDs matchable to trigger prose in §2/§3 (0 missing from prose, 0 missing from §5 table)
  - endpoints[]: 92/92 in the §4 table; side effects and applies_to scopes expressed in §3 narratives; all list-filter parameter names covered
  - entities[].fields[] structured content: defaults, initial values, null-until semantics (e.g., `charge_cents` until ACTIVE, computed settlement fields until first SUBMITTED), and the `common_fields: false` exception for `LedgerEntry`/`AccessEvent` (id + created_at only) all stated
  - sibling-branch symmetry: resolve FOR_CARDHOLDER vs FOR_MERCHANT, WEEKLY vs DAILY variants, PER_TRANSACTION vs AGGREGATE rounding, and the four replacement from-states all rendered with equal density — 0 asymmetric
- **Constants:** all embedded in business context (2500-cent provisional cap, 1000-cent minimum refund, 3-strike threshold, 30-day dispute window, 2500/3500/5000 fee tiers, 2x stolen surcharge, 1500 surrender discount, logical-clock default `2026-08-01T00:00:00Z`)
- No fuzzy/approximating wording (grep-verified); all 44 state values and 100 enum values appear as exact backticked strings; §2.2 block byte-identical to the canonical source.

The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were not opened or referenced.

## Step 5: Generate Unit Tests — 2026-08-14T16:34:10.000Z

All complete. Final state verified: 119 tests collect cleanly under pytest.

## Summary

**test_helpers/ files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1761_campus_card_meal_plan_management/test_helpers/`):
- `types.py` — 27 status/role enums + 17 entity TypedDicts; `LedgerEntry` and `AccessEvent` TypedDicts correctly omit `updated_at`/`version` (append-only per PRD §2.4)
- `api_client.py` — `ApiClient(GenericApiClient)` with 92 endpoint methods covering the full endpoint surface including `/_clock/set_current_utc`
- `api_errors.py` — 51-code `ApiErrorId` enum + HTTP status map registered with `set_error_http_status_map`
- `assertions.py` — 17 `assert_{entity}()` validators + `assert_account_balance_matches_ledger` invariant
- `factories.py` — 16 payload factories (input fields only)
- `constants.py` — PRD thresholds (MIN_REFUND_CENTS=1000, PROVISIONAL_DAILY_CAP=2500, FRAUD_SUSPENSION_THRESHOLD=3, DISPUTE_WINDOW_DAYS=30, replacement fee tiers 2500/3500/5000, surcharge ×2, surrender discount 1500)
- `test_users.py` — `TEST_USERS` for all 10 roles + per-instance builders; entity-backed `make_cardholder_headers`/`make_merchantuser_headers` used for every ownership-gated call
- `fixtures.py` — composite helpers across all five tiers (verified/provisional card chains, open-term enrollment, funded accounts, disputed purchases, close-pending/refund chains, merchant settlement chains, replacement chains)
- `__init__.py` — barrel export

**test_suite/ files written** (`.../test_suite/`): `conftest.py` + 11 test files (`test_01_registration_issuance_and_photos` … `test_11_security_envelope_and_reads`), 119 test functions total.

**Instances translated vs skipped:**
- Queue A (Difficulty): 20/20 instances, exactly 2 tests each = 40 tests
- Queue B (Corner): 79/79 non-stub instances, 1 test each = 79 tests
- Skipped: 0 — every instance passed the PRD-first two-condition filter (this PRD §2.10 explicitly pins the validation priority order, which keeps the priority-pair and role-beats-existence instances uniquely derivable)
- 9 `excluded_because:` stubs not translated; all 9 `difficulty_instance` cross-references verified to resolve

**Coverage audit output:**
- Design tags: 99 required → 99 found, 0 missing/under-covered, 0 unknown; every test has exactly one `Design:` line
- PRD citation pass: 187 quoted docstring spans, all survive whitespace-normalized literal grep of `PRD.md` (13 initial failures from dropped `**` bold markers / line-wrap / elision were fixed and re-verified)
- Interface check: all `test_helpers` imports resolve, all `api.*` calls match `ApiClient` methods, no `skip`/`skipif`/`xfail` markers
- `pytest --collect-only`: 119 tests collected, 0 errors

## Step 6: Generate Implementation — 2026-08-14T16:39:06.000Z

93 routes registered (92 spec endpoints + Flask's default static route). The implementation is complete and verified.

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1761_campus_card_meal_plan_management/workspace/implementation/`):

- `start.sh` — executable launcher: guarded `pip install` (no-op once Flask is importable), then `exec python3 app.py` in the foreground
- `requirements.txt` — `flask>=3.0,<4.0`
- `app.py` — Flask entry point, blueprint registration, `ApiError`/404/405/400/500 handlers producing the PRD error envelope, `0.0.0.0:$PORT` (default 10000)
- `db.py` — `Store` class: 17 entity dicts keyed by id + idempotency map + logical clock + monotonic seq; a module-level `store = Store()` so every fresh process starts completely empty
- `errors.py` — `ApiError` + all 51 error-id constants with their catalogued HTTP statuses
- `response.py` — success/error envelope (`meta.api_request_id` `req_*`, `api_request_timestamp`, `response_type`, `data`; pagination fields in `meta` for lists), 3-fractional-digit UTC timestamps from the logical clock
- `middleware.py` — `X-User-ID`/`X-User-Role` auth (401/403), body validators (strict int/bool/enum/datetime), path 404 helper, `pub()` serializer stripping internal `_`-keys, pagination (`limit` default 10, 1–100, `offset` default 0; created_at ASC + insertion-seq tiebreak)
- `services/core.py` — row creation/touch (version+1 per mutation), lazy card/grant EXPIRED evaluation, account auto-create/find helpers, 16-digit card-number minter
- `services/ledger.py` — pinned credit/debit direction map, `post_entry` with per-account `entry_sequence` and `running_balance_cents`, incremental balance == signed ledger sum
- `services/pricing.py` — all 12 calculations with `Decimal` ROUND_HALF_UP per-component rounding: WEEKLY/DAILY activation pricing, 5-step plan-change proration (deltas pinned at approval, posted at execution), replacement fee tiers (2500/3500/5000, faculty-staff free first, police waiver, ×2 stolen surcharge, 1500 surrender discount), PER_TRANSACTION vs AGGREGATE commission, refund variants (MIN_REFUND_CENTS=1000), cancellation credit, swipe threshold (strict <), provisional daily cap (2500, inclusive), fraud strike threshold (>=3)
- `services/cascades.py` — suspension cascade (excluding the reported-stolen card itself), offboarding (withdraw/graduate), enrollment activation/cancellation, term close (with immediate sub-1000 forfeiture) and settle cascades
- `routes/` — `clock.py`, `holders.py`, `cards.py` (cards+photos), `terms.py` (incl. advance-week execution sweep in created_at ASC with VOID on INSUFFICIENT_FUNDS/ENROLLMENT_CANCELLED), `plans.py`, `enrollments.py` (enrollments + change requests), `accounts.py` (accounts, funding, OCC adjustments, ledger reads, refunds), `transactions.py` (transactions + disputes with carryover marking), `access.py` (zones, grants, pinned 7-step access decision), `merchants.py` (merchants + settlement sweep/reject/resubmit with carried_from tracking)

**Architecture notes**: validation priority (§2.10) is enforced by explicit statement order in every handler — auth → role → ownership → body → path → body-refs → idempotency → state → OCC → cross-entity → fraud/SoD → temporal → uniqueness → funds. Ownership-vs-body ordering was deliberately fixed so `ERR_NOT_RESOURCE_OWNER` precedes body validation on all owner-scoped endpoints. Idempotent replay stores the original 201 payload per namespaced key; divergent reuse → 409. Dispute carryover uses internal `_excluded_by_settlement_id`/`_carried` markers (stripped from serialization) so restored transactions join the merchant's next sweep regardless of period, with `carried_from_settlement_id` pointing at the most recent non-REJECTED excluder.

**Logical clock & per-test-server boot**: the clock lives only in the process-local `Store`, defaults to exactly `2026-08-01T00:00:00Z`, never reads wall-clock; `POST /_clock/set_current_utc` (PlatformAdmin) sets it. All `created_at`/`updated_at`/proration/window/expiry evaluation reads this clock. Since state is purely in-memory dicts and `start.sh` launches a fresh process, every reboot wipes everything — verified explicitly (phase A created data, killed the server, rebooted via `bash start.sh`, phase B confirmed empty store and restored default clock).

**Self-check**: four smoke rounds (≈140 assertions) all pass against `bash start.sh` boots: full lifecycle CRUD, envelope/pagination shape, auth/role/ownership errors, photo review cycle, WEEKLY + DAILY proration with pinned numbers, plan-change execution and VOID paths, swipe exhaustion/reset, provisional cap boundary, fraud-strike cascade to suspension + fraud-review, replacement fee tiers incl. free/discounted variants, lazy card/grant expiry, dispute SoD + provisional credit permanence + clawback, refund AUTO_EXCLUDING_PROVISIONAL with residual CLOSE_PENDING, settlement sweep both commission modes, reject/resubmit, carryover with `carried_from_settlement_id`, term close forfeiture and settle blocking errors. All failures encountered during testing were test-side mistakes; the implementation matched the PRD on each investigation.

## Step 7: Run Tests and Iterate — 2026-08-14T16:55:48.000Z

All 8 rounds pass 119/119. The loop exit condition is met.

## Summary

**Iterations run:** 2 (initial 8-round sweep → fixes → verification 8-round sweep, plus one targeted 11-test verification run between them).

**Initial state:** 114/119 passing in every round; the same 5 tests failed in all 8 rounds (deterministic, not flaky).

**Tests deleted:** none — every failing assertion traced to verbatim PRD prose.

**Fixes applied to `test_suite/`:**
1. `/home/ubuntu/github/CodingPRD/tasks/task_1761_campus_card_meal_plan_management/test_suite/test_01_registration_issuance_and_photos.py` — added missing `activate_card` to the `test_helpers` import block (NameError in `TestCardParallelDimensions::test_provisional_activation_and_photo_approval_independence` and `test_lost_freeze_unfreeze_cycle_preserves_photo_dimension`).
2. Same file — `TestPhotoCycle::test_cardholder_cannot_review_photo`: `photos["data"][0]` → `photos[0]`; `get_success_data` already unwraps the envelope's `data`, so the list-endpoint result is a bare list (TypeError, not an implementation issue).
3. `/home/ubuntu/github/CodingPRD/tasks/task_1761_campus_card_meal_plan_management/test_suite/test_02_card_loss_theft_replacement_fraud.py` — `TestFraudEscalation::test_stolen_report_suspension_cascades_to_cards_accounts_grants`: assertions mis-translated the very PRD §3.2 sentence the test quotes ("deactivates the holder's **remaining** non-terminal cards"). The just-reported card stays `STOLEN_FROZEN` and its grant is suspended `CARD_FROZEN`, not `DEACTIVATED`/`REVOKED`; a holder may hold at most one non-terminal card, so the cascade's card-deactivation set is empty here. Assertions corrected to `STOLEN_FROZEN` / `SUSPENDED` and strengthened with `suspended_reason == "CARD_FROZEN"` (verbatim in PRD §3.2).

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:**
1. `/home/ubuntu/github/CodingPRD/tasks/task_1761_campus_card_meal_plan_management/workspace/implementation/routes/enrollments.py` — `create_change_request` was missing the priority-11 fraud/SoD guard; it returned `ERR_PLAN_CHANGE_WINDOW_CLOSED` (priority 12) for a suspended holder, violating PRD §2.10's fixed priority order ("suspended or fraud-flagged holders blocked from value-extending actions (`ERR_FRAUD_HOLD`, 409)" precedes the temporal-window checks). Added `ERR_FRAUD_HOLD` for `SUSPENDED` or fraud-flagged holders after the cross-entity state checks and before the add/drop window check; removed a now-duplicate holder load.

**Verification:** all 8 parallel rounds of the final sweep report 119/119 passed, 0 failed, 0 errors.

## Step 8: Finalize PRD — 2026-08-14T17:01:39.000Z

Done. The finalized PRD is at `/home/ubuntu/github/CodingPRD/tasks/task_1761_campus_card_meal_plan_management/workspace/PRD_FINALIZED.md`.

## Summary

**Line counts / delta:** PRD.md = 450 lines, PRD_FINALIZED.md = 450 lines (0% line-count delta). Exactly one line modified — a single sentence inserted inline into the existing §3.4 paragraph (no new sections, no other prose touched).

**Changes (one total):**
- **§3.4 (Enrollment, Activation Pricing, and Plan Changes) — insert** — Added one sentence to the plan-change-request paragraph pinning that submitting a plan change is a value-extending action: a holder whose `status` is `SUSPENDED` or whose `fraud_flag` is set is rejected with `ERR_FRAUD_HOLD` (409), checked at priority 11 after the enrollment-/term-/plan-state checks and before the add/drop-window check — `implementation/routes/enrollments.py:179-183` (guard condition) and `:184-186` (window check it precedes).

**Step 7 diff items requiring no edit (verified against implementation):**
- Item 1 (test_01 import fix) — pure test-side NameError; no behavioral content.
- Item 2 (test_01 `photos[0]` unwrap) — pure test-side double-unwrap of the §2.2 envelope; PRD and implementation agree on the envelope shape.
- Item 3 (test_02 stolen-report assertions) — PRD §3.2 already says verbatim that the cascade "deactivates the holder's **remaining** non-terminal cards"; confirmed `implementation/routes/cards.py:144,151-152` + `implementation/services/cascades.py:45-50` keep the just-reported card `STOLEN_FROZEN` (via `exclude_card_id`) and suspend its grants with `CARD_FROZEN`. Pure test-side misreading.

**Pre-edit search log (NO-NEW-MISMATCH RULE) for the single edit:**
- **(a) Subject:** whether plan-change-request *submission* by a suspended/fraud-flagged holder yields `ERR_FRAUD_HOLD`, and the check's position in the guard order.
- **(b) Impl paths enumerated and read/grepped:** `enrollments.py:155-210` (create_change_request — the Step 7 fix site; condition `status == "SUSPENDED" or fraud_flag`; no `ERR_HOLDER_NOT_ACTIVE` check exists in this endpoint); `transactions.py:146-148` (create_transaction fraud hold, already covered by §3.5); `holders.py:114-115` (reinstate guard, already covered by §3.2 verbatim); `accounts.py` (grep: zero fraud/SUSPENDED/HOLDER_NOT_ACTIVE matches — funding, adjustments, refund-request creation do **not** gate on fraud); `transactions.py:251-296,427-444` (dispute create/withdraw — no fraud gate); `cards.py` (grep: `ERR_FRAUD_HOLD` absent; only `ERR_HOLDER_NOT_ACTIVE` at :102, :179); `enrollments.py:257-324` (approve/deny/withdraw — no fraud-hold re-check); `test_suite/test_04_plan_changes.py:370-406` (auxiliary evidence: `ERR_FRAUD_HOLD` must beat `ERR_PLAN_CHANGE_WINDOW_CLOSED`).
- **(c) Wording adjustment:** the sentence is deliberately scoped to *submission* only, echoes the impl's exact condition, and anchors ordering via "priority 11" rather than redefining the global phrase "value-extending actions" — a generalized edit (e.g., enumerating actions in §2.10 or claiming all value-extending actions check) would have falsely swept in funding, refund requests, and disputes, none of which check. Approval/withdrawal paths are left untouched since the implementation does not re-check fraud hold there.

## Step 9: Complete PRD — 2026-08-14T17:21:05.000Z

All edits verified. The diff is exactly the 30 intended hunks with no collateral changes. Final report:

## Summary

**Source vs output:** `PRD_FINALIZED.md` (450 lines / 80,159 chars) → `PRD_COMPLETED.md` (452 lines / 84,098 chars). Char delta: **+3,939**. 30 diff hunks, all inline inserts/revisions; no new sections.

**Counts:** 25 ambiguity-pins, 7 mismatch-revisions (32 distinct pins total; some hunks carry two).

**Changes** (`{PRD section} — {insert|revise} — {ambiguity|mismatch} — {what} — {impl ref}`):

- §2.2 — insert — ambiguity — unrouted path / unsupported method → `ERR_NOT_FOUND` 404; absent/unparseable body treated as `{}`; non-object body → `ERR_VALIDATION`; unexpected failure → `ERR_INTERNAL` 500 — app.py:39-57, middleware.py:46-52
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`, negative `offset` → `ERR_VALIDATION` — middleware.py:144-165
- §2.3 — revise — ambiguity — list sort ties broken by creation (insertion) order — middleware.py:166
- §2.4 — revise — ambiguity — `version` starts at 1 at creation — services/core.py:19-28
- §2.5 — insert — ambiguity — all server-generated timestamps (`api_request_timestamp`, `created_at`, `updated_at`, `activated_at`, `attempted_at`) read the logical clock — response.py:14-16, services/core.py:22
- §2.5 — insert — ambiguity — clock endpoint accepts any parseable instant (backward moves allowed) — routes/clock.py:17-18
- §2.8 — insert — ambiguity — idempotency keys scoped per operation kind; payload identity = full body (+ account id for funding, + role for transactions) — routes/accounts.py:126-133, routes/transactions.py:90-97
- §3.1 — revise — ambiguity — issuance `expires_at` at/before clock → `ERR_VALIDATION` — routes/cards.py:48-49
- §3.1 — insert — ambiguity — photo submission also requires `photo_status` ∈ {NOT_SUBMITTED, REJECTED}, else `ERR_INVALID_STATE_TRANSITION` — routes/cards.py:254-256
- §3.1 — revise — mismatch — activation precondition order pinned as expiry → holder → photo (was listed holder → photo → clock) — routes/cards.py:96-105
- §3.2 — revise — ambiguity — unfreeze of PENDING_PHOTO/ACTIVE card → `ERR_INVALID_STATE_TRANSITION` — routes/cards.py:171-176
- §3.2 — insert — ambiguity — strike threshold suspension fires only while holder ACTIVE; strikes on non-ACTIVE holders increment count without cascade/flag — services/cascades.py:53-61
- §3.2 — revise — ambiguity — fraud review has no holder-state precondition; `notes` accepted but not persisted — routes/holders.py:150-159
- §3.2 — revise — ambiguity — replacement payload `police_report_number` persisted on retired card; APPROVED-photo successor carries `photo_status` APPROVED — routes/cards.py:207-214
- §3.3 — revise — ambiguity — `weekly_swipe_allowance` required on creation even when `is_unlimited_swipes` true — routes/plans.py:27
- §3.4 — revise — ambiguity — assignment requires term SCHEDULED or OPEN, else `ERR_TERM_NOT_OPEN`; check order holder → plan → term pinned — routes/enrollments.py:46-51
- §3.4 — revise — mismatch — change-request submission checks reordered to impl (term OPEN → enrollment ACTIVE → plan PUBLISHED [newly pinned] → fraud hold → window → same-plan → eligibility → pending) — routes/enrollments.py:172-194
- §3.4 — revise — mismatch — approval re-check order: term OPEN before window before effective-week (was window first) — routes/enrollments.py:267-273
- §3.4 — insert — ambiguity — week-advance swipe reset is a no-op (no version bump) when count already 0 — routes/terms.py:185-189
- §3.5 — insert — ambiguity — MerchantUser omitting / PointOfSale supplying `merchant_id` → `ERR_VALIDATION` — routes/transactions.py:76-83
- §3.5 — insert — ambiguity — "current term" = earliest-created OPEN term; no OPEN term → swipe/DINING_DOLLARS postings fail `ERR_TERM_NOT_OPEN` — routes/transactions.py:41-46, 113-129
- §3.5 — revise — ambiguity — funding and adjustments respond 201 with the created LedgerEntry; `direction` also accepts short spellings CREDIT/DEBIT — routes/accounts.py:136-164
- §3.6 — revise — ambiguity — `resolution_note` required on resolve (`ERR_VALIDATION` when omitted) — routes/transactions.py:393
- §3.6 — insert — ambiguity — swipe dispute resolved FOR_CARDHOLDER posts no ledger entry and does not restore the consumed swipe — routes/transactions.py:403-413
- §3.6 — revise — ambiguity — dispute withdrawal never adds a fraud strike, unlike a merchant win — routes/transactions.py:427-444
- §3.7 — revise — mismatch — term-close forfeiture: FORFEIT entry posted only when balance positive; zero balance → FORFEITED with no entry — services/cascades.py:145-155
- §3.7 — revise — mismatch — same positive-balance-only FORFEIT rule at term settle — services/cascades.py:168-178
- §3.8 — insert — ambiguity — grant creation requires card `ACTIVE`, else `ERR_CARD_NOT_ACTIVE` — routes/access.py:131-132
- §3.9 — revise — ambiguity — `commission_bps` bounds 0–2000 inclusive — routes/merchants.py:37
- §3.9 — revise — ambiguity — termination admitted only from ACTIVE/SUSPENDED (PENDING_CONTRACT → `ERR_INVALID_STATE_TRANSITION`) — routes/merchants.py:115-117
- §3.9 — revise — mismatch — settlement period overlap evaluated as closed-interval intersection at timestamp precision (was "share any day") — routes/merchants.py:146-155
- §3.9 — revise — mismatch — settlement approval moves every linked transaction still `POSTED` to SETTLED (was "every linked transaction") — routes/merchants.py:299-302

**Verified already-pinned (no change needed):** all 92 endpoint paths/role lists in §4 match the routes exactly; all 51 error ids and HTTP statuses match errors.py; all 12 calculations (activation pricing, cancellation credit, five-step plan-change proration, replacement fee tiers, both commission modes, refund variants, provisional cap) match pricing.py; ledger replay/entry-sequence/running-balance rules match ledger.py; access-decision evaluation order and grant ranking match access.py; 201/200 semantics match every handler.

Output file: `/home/ubuntu/github/CodingPRD/tasks/task_1761_campus_card_meal_plan_management/workspace/PRD_COMPLETED.md`

## Pipeline Complete — 2026-08-14T17:21:05.000Z

All 9 steps done. Final state: 119/119 tests passing across all 8 parallel stability rounds; PRD_COMPLETED.md exists at workspace/PRD_COMPLETED.md.
