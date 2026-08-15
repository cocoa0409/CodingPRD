# Worklog — task_1542_housing_cooperative_board_share_transfer

## Step 1: Create Task Directory — 2026-08-13T19:12:00.000Z

Task directory `tasks/task_1542_housing_cooperative_board_share_transfer/` and `workspace/` pre-created and pre-assigned by the pipeline launcher; Step 1 treated as DONE per instructions.

## Step 2: Generate Scaffold — 2026-08-13T19:38:00.000Z

Subagent generated all three scaffold artifacts from the verbatim scenario (NY housing co-op: share allocation & maintenance charges, purchase application & board interview/approval, sublet policy & fees, flip tax, underlying mortgage & refinancing, arrears & proprietary-lease termination, alteration agreements, annual meeting & elections). The first subagent turn ended mid-planning without writing files; it was resumed and completed generation, then stopped again during its own lint-fix pass.

Orchestrator-side completion: ran `scaffold_lint.py` — initial verdict was 35 violations, all rule (f) FK_REVERSE_UNREACHABLE (the lint's collection-segment heuristic only recognizes flat `<prefix>/<segment>/{id}` paths; the scaffold's nested `/cooperatives/{cid}/<segment>` design registered no segments). Applied the lint's own sanctioned remedy: added 30 purely-additive flat alias GET endpoints (one single-resource GET + one FK-filterable list GET per FK-bearing child entity, 15 entities × 2), preserving the nested design that all 438 §1.8/§1.9 test-recipe calls reference. Re-ran lint:

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
Coverage: 98 endpoints | 16 entities | 18 §1.8 instances | 32 §1.9 instances | 438 calls scanned
```

Final scaffold profile: complexity_profile primary=compliance_audit, secondary=multi_party_negotiation, layers=[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, scheduled_deferred_actions, derived_field_reconciliation], topology=hybrid, role_model=segregation_of_duties. 16 entities (Cooperative, Unit, Shareholder, ShareLedgerEntry, ChargeSchedule, MaintenanceCharge, Payment, ArrearsAction, PurchaseApplication, Interview, Resolution, ResolutionVote, SubletAgreement, AlterationAgreement, Meeting, Ballot); 12 state machines; 9 calculations (maintenance_monthly_charge, flip_tax, arrears_interest_accrual, arrears_late_fee, sublet_monthly_fee, quorum_check, election_tally, refinance_payment_estimator, buyer_liquidity_requirement); 11 validations; 22 error codes; 5 roles (PlatformAdmin, BoardOfficer, BoardMember, ManagingAgent, Shareholder).

## Step 3: Copy Shared Files — 2026-08-13T19:47:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-13T20:07:00.000Z

PRD generation complete. Output written to `workspace/PRD.md`. The two difficulty/corner design files were not opened or referenced.

## Summary (verbatim from subagent)

**PRD line count:** 360 lines

**Section list:**
- 1. Introduction (2 paragraphs, NY co-op business-context angle)
- 2. Global Specifications & System-Wide Principles — 2.1 User and Role-Based Access Control; 2.2 API Response Structure (verbatim fixed block); 2.3 Pagination; 2.4 Resource Identity, Common Fields, and the Cooperative-Scoped URL Hierarchy; 2.5 The Logical Clock and Scheduled System Behavior; 2.6 Monetary Representation, Precision, and Rounding; 2.7 Share Conservation and the Cooperative Version Counter; 2.8 Optimistic Concurrency Control; 2.9 Validation Order and Error Semantics; 2.10 Cross-Cooperative Flat Read Aliases
- 3. Business Logic & Workflows — 3.1 Establishing the Building (units/shareholders/ledger); 3.2 Board Resolutions and Voting Discipline; 3.3 Budgeting, Charge Schedules, and the Monthly Maintenance Cycle; 3.4 Payments, Arrears, and Termination of the Proprietary Lease; 3.5 Selling a Unit (application → certification → interview); 3.6 Purchase Decision, Transfer Recording, Flip Tax; 3.7 Subletting under the House Policy; 3.8 Renovations under an Alteration Agreement; 3.9 Meetings, Quorum, and Board Elections
- 4. Endpoint Definitions (4-column table)
- 5. Error Code Catalogue (2-column table)

**Coverage counts:**
- Entities: 16 of 16 covered (117 scaffold fields, all present verbatim in backticks)
- Endpoints: 98 of 98 in the §4 table (68 nested + 30 flat aliases), each verified with exact method, path, and role-set match against the scaffold
- Calculations: 9 of 9 expressed as precise prose formulas (maintenance allocation with both variants + residual absorber rule, flip tax both variants, daily arrears interest with 86,400-second day flooring and non-compounding principal basis, one-time late fee with exact grace boundary, 15% sublet fee, quorum ceiling-division check with equality-counts boundary, simplified cumulative election tally with both tie-breaks, interest-only refinance estimator, buyer DTI/liquidity with 7% mortgage assumption)

**Transition/endpoint confirmation:** Every §1.5 endpoint (all 98, including the logical-clock endpoint and all 30 flat cross-cooperative aliases with their full filter-parameter sets enumerated in §2.10) is documented, and every §1.2 state-machine edge (62 from→to pairs across 12 machines) is described in prose with preconditions, error IDs, and side effects — verified mechanically with zero uncovered pairs.

**Hard contract reports:**
- Contract 1 (Field-Name Coverage): 117 entity fields / 86 endpoint input names / 14 path params — 0 missing — **PASS**
- Contract 2 (Rule Coverage): 11 validations with priority ordering expressed as an ordered 11-step evaluation ladder in §2.9; 2 OCC rules expressed with write operation + `expected_cooperative_version` + `ERR_STALE_COOP_VERSION` (412); 62/62 transition edges fully expressed; 9/9 calculations; all validation conditions matchable to error IDs; all endpoint side effects expressed; field defaults/initials (policy defaults, `votes_required` = 3 of 5, startup clock 2026-08-01T00:00:00Z, etc.) reconstructible — **PASS**
- Contract 3 (§3 Path Purity): 576 backticked tokens scanned in §3, 0 path/method violations — **PASS**

## Step 5: Generate Unit Tests — 2026-08-13T20:47:00.000Z

All checks pass. The generation is complete and fully verified. (Verbatim subagent summary follows.)

**test_helpers/ (9 modules)** — all under `test_helpers/`:
- `types.py` — 16 entity TypedDicts + 24 status/role enums (all entities carry id/created_at/updated_at/version per PRD §2.4 "No entity in this API is exempt")
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per §4 endpoint: all nested routes plus all 30 flat cross-cooperative read aliases
- `api_errors.py` — `ApiErrorId` (22 ids) + HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*`, `assert_charge_money_conservation`, `assert_shares_conserved`, strict 3-fractional-digit timestamp check
- `factories.py`, `constants.py` (thresholds: financing cap 8000bps, DTI 2800bps, sublet fee 1500bps, $1M insurance min, 3-of-5 votes, cure windows), `test_users.py` (opaque-role constants + `make_shareholder_headers` for the entity-backed role)
- `fixtures.py` — composite chains: `setup_approved_schedule`, `setup_multi_unit_approved_schedule`, `make_charge_past_due` (reads the server-assigned `due_date` instead of assuming the 1st — PRD only says "typically the first of the month"), `setup_delinquent_shareholder`, full purchase pipeline to APPROVED, `setup_completed_sublet` (walks a sublet through ACTIVE→COMPLETED via clock), meeting/ballot envs

**test_suite/ (7 files + conftest.py, 68 tests total)**:
| File | Tests |
|---|---|
| test_01_cooperative_foundation.py | 10 |
| test_02_charge_schedules_and_budgeting.py | 9 |
| test_03_payments_arrears_and_termination.py | 8 |
| test_04_purchase_application_review.py | 11 |
| test_05_share_transfer_and_flip_tax.py | 7 |
| test_06_sublets_and_alterations.py | 9 |
| test_07_meetings_resolutions_and_rbac.py | 14 |

**Queue A (§1.8 difficulty): 18/18 instances translated, 36 tests** (exactly 2 per instance). **Queue B (§1.9 corner): 32/32 non-stub instances translated, 32 tests; 0 skipped.** The one stub (`Corner/calculations/arrears_late_fee_boundary_exact_grace_day`) was not translated per spec; its `excluded_because` pointer (`boundary_precision_check/arrears_termination_threshold_boundary`) resolves to a real queue-A instance.

**Deviations from the design YAMLs (all forced by the PRD-first rule):**
1. **Design arithmetic errors corrected**: `maintenance_pro_rata_vs_equal_split_divergence` asserted 166667/333333/500000 — off by 10×; PRD §3.3's formula yields 1666667/3333333/5000000, which the tests assert. Same for `charge_schedule_approval_cascade_to_arrears` (budget 12000000 → monthly 1000000, not 100000; exact interest 165 and outstanding 1005165 asserted).
2. **Refinance payload key**: design used `new_rate_bps`; PRD §3.2 names `rate_bps_new` — tests use the PRD key. The `delta_vs_current_cents` payload key is never named in the PRD, so the delta-persistence assertion was replaced with the PRD-verbatim "every `APPROVED` charge schedule stays exactly in place" no-rebudget test.
3. **Sublet gap setup hardened**: design's first-sublet window lay entirely before the startup clock (ambiguous activation); the fixture drives it through ACTIVE→COMPLETED with two clock advances instead.
4. **Sublet standing-gate error ambiguity** (PRD names no specific error_id for a delinquent sublet submit): test asserts `ERR_CROSS_ENTITY_VIOLATION` or `ERR_INVALID_STATE` with HTTP 409/422 per the error-precedence silence pattern.

Final audits all green: every test docstring ends with exactly one verbatim `Design:` tag resolving to a real instance; 109 quoted PRD citation fragments verified verbatim against PRD.md; no skip/xfail markers; no scaffold references; all modules compile and import cleanly.

## Step 6: Generate Implementation — 2026-08-13T20:52:00.000Z

Implementation complete and verified. (Verbatim subagent summary follows.)

## File list (all under `workspace/implementation/`)

| File | Lines | Purpose |
|---|---|---|
| `start.sh` | 10 | Foreground launcher: guarded `pip install` (no-op when Flask present), `exec python3 app.py`, reads `$PORT` (default 10000), binds 0.0.0.0 |
| `requirements.txt` | 1 | `flask>=3.0,<4.0` |
| `app.py` | 52 | App assembly, blueprint registration, ApiError/404/405/500 envelope handlers |
| `db.py` | 39 | In-memory dict store (16 entity tables) + UUID/sequence minting; starts empty every boot, zero seeding |
| `errors.py` | 33 | `ApiError` + all 21 catalog error IDs |
| `response.py` | 42 | Envelope: `meta{api_request_id, api_request_timestamp}`, `response_type`, `data`; list meta adds `limit/offset/total_count/has_more` |
| `middleware.py` | 28 | `X-User-ID`/`X-User-Role` extraction (400 `ERR_MISSING_CONTEXT_HEADER`), role gating (403 `ERR_UNAUTHORIZED_ROLE`) |
| `util.py` | 179 | ISO-8601 parse/format (3-fraction-digit Z), body field validators (400 `ERR_INVALID_REQUEST` / `ERR_INVALID_ENUM`), pagination (limit 1–100 default 10, offset 0) |
| `domain.py` | 824 | All business logic |
| `routes/core.py` | 265 | Cooperatives, `_clock/set_current_utc`, units, shareholders, share ledger |
| `routes/charges.py` | 275 | Charge schedules (OCC), maintenance charges, payments/void, arrears actions |
| `routes/purchase.py` | 390 | Purchase applications (submit/certify/request-info/submit-info/schedule-interview/record-transfer/withdraw), interviews |
| `routes/resolutions.py` | 201 | Resolutions, votes, withdraw, nested votes list |
| `routes/agreements.py` | 335 | Sublets (policy checks) and alterations (safety checks) |
| `routes/meetings.py` | 203 | Meetings (notice/open/close), ballots with re-vote-replaces |
| `routes/flat.py` | 284 | All 30 flat cross-cooperative alias routes |

Total: ~3,161 lines.

## Counts
- **Endpoints: 98/98** — verified programmatically via Flask's url_map (68 nested + 30 flat aliases). Flask's static-over-dynamic ranking resolves `/cooperatives/units` vs `/cooperatives/{cid}` correctly.
- **State machines: 12** — ChargeSchedule, MaintenanceCharge, Payment, ArrearsAction, Shareholder.standing, PurchaseApplication (incl. INFO_REQUESTED cycle), Interview, Resolution, SubletAgreement, AlterationAgreement, Meeting (compound preparation × quorum), Ballot.
- **Calculations: 9** — maintenance_monthly_charge (PRO_RATA/EQUAL_SPLIT with largest/earliest-unit residual absorption), flip_tax (GROSS_PERCENT/PER_SHARE), arrears_interest_accrual (simple daily, `ceil` day count, principal = base+late_fee−paid, catch-up-before-payment), arrears_late_fee (one-time flat), sublet_monthly_fee (15% of current base), quorum_check (ceiling division, `>=` boundary, recompute-from-scratch), election_tally (simplified cumulative with cast-order/lexicographic tie-breaks), refinance_payment_estimator (delta persisted to payload_json), buyer_liquidity_requirement (DTI ≤ 2800 bps + 12-month carrying-cost liquidity).

Key semantics honored: logical clock defaulting to 2026-08-01T00:00:00Z drives every temporal transition; OCC `expected_cooperative_version` (412, checked last) on schedule-create and record-transfer; validation ladder auth → role → ownership → existence → state → safety → cross-entity → temporal → constraint → fiscal → OCC; segregation of duties (certifier not on panel; resolution opener cannot vote); deciding votes on gated resolutions (APPROVE_PURCHASE fiscal gates, wet-over-dry ack) are rejected atomically without recording; termination cascade supersedes ledger entries, terminates sublets, abandons alterations, withdraws seller applications; share-conservation `ERR_SHARES_MISMATCH` on ledger writes.

## Boot verification
- `PORT=18814 bash start.sh` from `./implementation/` → server up in ~2s, fresh-boot `GET /cooperatives` returns `total_count: 0` (no seeding), create/read round-trip works.
- Two end-to-end smoke suites passed against a live server covering: auth errors, envelope shape, pagination, unit/shareholder/ledger flows, schedule approval + charge generation (pro-rata and equal-split with residual), supersede/waive cascade, partial/full/over-payment, void, past-due + late fee + interest arithmetic (verified exact cent values), arrears ladder with escalation spawn and termination-resolution gate, full purchase pipeline with flip tax under both policies, DTI/liquidity gate rejections, sublet policy (max years, gap, overlap), alteration safety and wet-over-dry ack gate, interview no-show, meeting quorum met/failed + auto-adjourn, re-vote invalidation, and flat alias reads.

One design note: `arrears_balance_cents` sums outstanding over issued charges only (PENDING excluded) — the PRD's cure semantics ("balance returns to zero" cures ISSUED actions) are only satisfiable under that reading.

## Step 7: Run Tests and Iterate — 2026-08-13T21:12:00.000Z

All 8 rounds pass cleanly (68/68 each). The verification sweep is complete. (Verbatim subagent summary follows.)

**Iterations run:** 2 (one baseline sweep surfacing 2 deterministic failures, one verification sweep after fixes — all 8 rounds × 68 tests passed).

**Tests deleted:** None. Both failing tests traced to verbatim PRD prose and were uniquely derivable.

**Fixes applied to `test_helpers/`:** None (helpers were correct; `send_notice` was already defined and exported).

**Fixes applied to `test_suite/`:**
- `test_suite/test_07_meetings_resolutions_and_rbac.py` — added missing `send_notice` to the `from test_helpers import (...)` list. `test_notice_sent_leaves_quorum_pending` used the helper without importing it (`NameError`). The test's assertions are verbatim PRD §3.9 (notice moves `preparation_state` to `NOTICE_SENT`, leaves `quorum_state` `QUORUM_PENDING`); only the import was broken.

**Fixes applied to `implementation/`:**
- `workspace/implementation/domain.py`
  - `pre_pass_gates()` — removed the two `ERR_CROSS_ENTITY_VIOLATION` vote-blocking gates for `APPROVE_PURCHASE` (application not in `INTERVIEW_SCHEDULED`; interview not `COMPLETED`/`FAVORABLE`). PRD §3.6 states verbatim "even a passed resolution does not approve an unqualified buyer", and §3.2 makes closure automatic at `votes_required` — so the interview/state qualifications gate the cascade, not the vote. Kept the two fiscal gates (`debt_to_income_bps > 2800`, liquidity < 12 × carrying costs) as vote-rejecting `ERR_FISCAL_THRESHOLD_VIOLATION` checks, since PRD §3.6 explicitly assigns those failures HTTP 422.
  - `apply_resolution_passed()` — `APPROVE_PURCHASE` now fires the `INTERVIEW_SCHEDULED → APPROVED` transition (stamping `deciding_resolution_id`) only when the application is in `INTERVIEW_SCHEDULED` and the latest interview is `COMPLETED` with `FAVORABLE` outcome; otherwise the passed resolution leaves the application untouched (e.g., stays `UNDER_REVIEW` after an `UNFAVORABLE` interview), exactly as PRD §3.6 requires.

**Result:** 8/8 parallel rounds clean, 68/68 tests passing per round under per-test-server isolation. Verified by orchestrator: all 8 `results.{1..8}.json` files show passed 68/68, failed 0.

## Step 8: Finalize PRD — 2026-08-13T21:25:00.000Z

Done. The diff is confined to a single paragraph (§3.6, line 190), rewritten in place to match the implementation's final semantics. (Verbatim subagent summary follows.)

**Line counts / delta:** `PRD.md` 360 lines → `PRD_FINALIZED.md` 360 lines (0.0% line delta; one paragraph revised inline, no sections added or removed).

**Changes (one logical edit, applied as two inline revisions to the same §3.6 paragraph):**
- §3.6 — revise — Buyer-qualification enforcement for `APPROVE_PURCHASE` split into two mechanisms: (1) the two fiscal thresholds (`debt_to_income_bps > 2800`, liquidity < 12 × carrying costs) are enforced at closure — the vote that would bring `votes_for` to `votes_required` is rejected with `ERR_FISCAL_THRESHOLD_VIOLATION` (HTTP 422), the vote is not recorded, tallies stand, and the resolution stays `OPEN`; (2) the interview/state qualification never blocks voting — it gates only the post-pass cascade, which moves the application `INTERVIEW_SCHEDULED → APPROVED` and stamps `deciding_resolution_id` only when, at pass time, the application sits in `INTERVIEW_SCHEDULED` and its latest interview is `COMPLETED` with `FAVORABLE` outcome, otherwise leaving the application untouched. — `implementation/domain.py:448-474` (`pre_pass_gates`), `domain.py:497-511` (`apply_resolution_passed`), invocation timing at `implementation/routes/resolutions.py:120-146`.

**Step 7 items producing no edit:** the `test_suite` fix (missing `send_notice` import in `test_07_meetings_resolutions_and_rbac.py`) is a pure fixture bug — §3.9 already states the notice/quorum behavior verbatim; no PRD silence.

**Pre-edit search log:**
- (a) Subject: which `APPROVE_PURCHASE` buyer qualifications block the deciding vote vs. gate the post-pass cascade.
- (b) Paths enumerated and read: `implementation/routes/resolutions.py:97-164` (`cast_vote` — gates run only under `if would_pass`, gate failure raises before the vote row/counters, FAILED branch cascades only for sublet/alteration kinds); `implementation/domain.py:448-489` (`pre_pass_gates` — APPROVE_PURCHASE keeps exactly the two fiscal gates; the APPROVE_ALTERATION wet-over-dry gate belongs to §3.8 and was left unclaimed by my wording); `implementation/domain.py:492-517` (`apply_resolution_passed` — conditional APPROVE_PURCHASE/REJECT_PURCHASE cascades); `implementation/domain.py:435-441` (`latest_interview` — latest by creation sequence); `implementation/routes/purchase.py:238-299` (`record_transfer` — requires `APPROVED`); plus a repo-wide grep over `APPROVED` / `deciding_resolution_id` / `FAVORABLE` / `INTERVIEW_SCHEDULED` confirming no other path approves an application or stamps `deciding_resolution_id`, and that all paths bouncing an application out of `INTERVIEW_SCHEDULED` (UNFAVORABLE completion, cancel, no-show, withdraw, lease termination) leave the cascade's precondition false.
- (c) Wording adjustments from enumeration: scoped the fiscal rejection to "the vote that would bring `votes_for` to `votes_required`" rather than any vote (non-deciding votes are never gated); added "that vote is not recorded, the tallies stand, and the resolution remains `OPEN`" to pin the atomicity; changed "the application's interview" to "its latest interview" (impl picks the most recently created interview when several exist); avoided any universal claim about cross-entity gates on other resolution kinds (e.g., `APPROVE_SCHEDULE`'s still-`DRAFT` check is cascade-gated in the impl while §2.9 item 7 lists it as an `ERR_CROSS_ENTITY_VIOLATION` example — not a Step 7 site, so left untouched and unclaimed).

File produced: `workspace/PRD_FINALIZED.md`

## Step 9: Complete PRD — 2026-08-13T21:52:00.000Z

Done. `PRD_COMPLETED.md` produced at `workspace/PRD_COMPLETED.md`. (Verbatim subagent summary follows.)

**Source vs output:** PRD_FINALIZED.md 360 lines / 69,475 chars → PRD_COMPLETED.md 360 lines / 73,370 chars (+3,895 chars, 0 line delta — every change is an in-paragraph insert/revision, no new paragraphs or sections).

**Counts:** 29 logical changes in 25 diff hunks — 21 ambiguity-pins, 8 mismatch-revisions.

**Change log** (PRD section — insert|revise — ambiguity|mismatch — what changed — impl ref):

- §2.1 — revise — ambiguity — SoD rule #2 pinned: the operator who opened a resolution under `BoardOfficer` may not cast a `BoardMember` vote on it (opener's `X-User-ID` recorded at creation) — routes/resolutions.py:71,107-113
- §2.2 — insert — ambiguity — unrouted path → `ERR_NOT_FOUND` 404; known path + unsupported method → `ERR_NOT_FOUND` with HTTP 405; unhandled failure → `ERR_INTERNAL` 500 (uncatalogued id) — app.py:34-44
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`, negative `offset`, non-integer int-filter → `ERR_INVALID_REQUEST` 400; no-match filters yield empty page; `created_at` ties break by creation order — util.py:167-179, routes/core.py:24-41, domain.py:128
- §2.4 — insert — ambiguity — `version` starts at 1 at creation — domain.py:89
- §2.5 — insert — ambiguity — clock set unconditionally (no monotonicity check); all domain-entity timestamps (`created_at`, `updated_at`, `submitted_at`, `issued_at`, `posted_at`, `opened_at`, `closed_at`, `cast_at`, `effective_at`, `transferred_at`, `completed_at`) read from the logical clock — routes/core.py:98-106, domain.py:82-101
- §2.9 — revise — mismatch — validation order: existence (404) now step 3, ownership (403) step 4 (impl checks path existence before ownership); ownership list extended to draft-creation endpoints — routes/purchase.py:120-121, routes/agreements.py:102-103
- §2.9 — insert — ambiguity — structural failures cover non-JSON/non-object bodies; undefined body fields are ignored — util.py:55-63
- §3.1 — insert — ambiguity — non-positive `shares_allocated` → `ERR_INVALID_REQUEST` 400 — routes/core.py:121-122
- §3.1 — revise — mismatch — `arrears_balance_cents` sums only charges that have left `PENDING`, over units owned via `ACTIVE` ledger entries (PRD said "every maintenance charge") — domain.py:158-164
- §3.2 — insert — ambiguity — vote endpoint responds HTTP 201 with the created `ResolutionVote` — routes/resolutions.py:164
- §3.2 — revise — ambiguity — refinance payload fields pinned: `rate_bps_new` (default current rate), `principal_cents_new` (also accepts `underlying_mortgage_principal_cents`, default current principal); audit persisted as `annual_payment_cents_new` / `delta_vs_current_cents`; projection uses the new principal — domain.py:522-540
- §3.2 — revise — ambiguity — passed `ISSUE_ARREARS_ACTION` escalates the shareholder's most recently issued still-`ISSUED` action; no-op if none — domain.py:554-560
- §3.3 — insert — ambiguity — `effective_from` not strictly before `effective_to` → `ERR_TEMPORAL_CONFLICT` 422 — routes/charges.py:44-45
- §3.3 — revise — ambiguity — billing month participates iff its first day is ≥ `effective_from` and < `effective_to`; `due_date` is the first instant (00:00:00 UTC) of the billing month — domain.py:299-312,343-361
- §3.3 — insert — ambiguity — a charge whose `outstanding_cents` stands at zero settles to `PAID` on clock evaluation — domain.py:288-290
- §3.4 — insert — ambiguity — payments accepted only against `ISSUED`/`PARTIALLY_PAID`/`PAST_DUE`; `PENDING` → `ERR_INVALID_STATE` 409; `PAID`/`WAIVED` → `ERR_ALREADY_TERMINAL` 409 — routes/charges.py:129-133
- §3.4 — insert — ambiguity — interest accrued to the current logical instant before the exceeds-outstanding check; partial payment on `PAST_DUE` leaves it `PAST_DUE` — routes/charges.py:136,154-157
- §3.4 — revise — mismatch — voiding allowed whenever the payment is still `POSTED` (dropped the not-PAID/negative-`paid_cents` proviso impl never enforces); already-`VOIDED` → `ERR_ALREADY_TERMINAL` — routes/charges.py:163-187
- §3.4 — revise — mismatch — interest day count is ceiling (rounded-up) days past grace, not "complete days" (PRD sentence was self-contradictory) — domain.py:251
- §3.4 — insert — ambiguity — manual `TERMINATION_NOTICE` escalation without a PASSED resolution → `ERR_CROSS_ENTITY_VIOLATION` 422; clock-driven escalation defers (stays `ISSUED`) — domain.py:644-655,810-821
- §3.5 — revise — ambiguity — in-flight-application conflict → `ERR_BUSINESS_CONSTRAINT` 422; positive-price rule enforced at creation and submission with `ERR_INVALID_REQUEST` 400 — routes/purchase.py:72-73,128-144
- §3.5 — insert — ambiguity — `info_request_notes` / `info_payload` accepted but not persisted — routes/purchase.py:167-193
- §3.6 — insert — ambiguity — current-month maintenance comes from the most recently created non-`WAIVED` charge for that billing month (zero if none) — domain.py:409-423
- §3.7 — insert — ambiguity — unit already `SUBLET` → `ERR_SUBLET_POLICY_VIOLATION` 422 — routes/agreements.py:124-126
- §3.7 — insert — ambiguity — calendrical year arithmetic clamps Feb 29 → Feb 28 in non-leap target years — util.py:43-48
- §3.7 — revise — mismatch — failed resolution rejects only `SUBMITTED` sublets; outright officer rejection covers `SUBMITTED`/`APPROVED` (PRD claimed both paths reject `APPROVED`) — routes/resolutions.py:152-156, routes/agreements.py:146-158
- §3.8 — revise — ambiguity — missing `wet_over_dry_ack` rejects the deciding vote (not recorded, tallies stand, resolution stays `OPEN`), mirroring §3.6 fiscal gates — domain.py:475-489, routes/resolutions.py:126-127
- §3.9 — insert — ambiguity — ballots accepted while `SCHEDULED` or `IN_SESSION`; terminal meeting → `ERR_ALREADY_TERMINAL` 409 — routes/meetings.py:144-145
- §3.9 — revise — mismatch — ballot carries no `cast_at` field; cast instant is the common `created_at`, and the tally tie-break is by creation order — routes/meetings.py:162-171, domain.py:718-745
- §4 — revise — mismatch — "All endpoints live under `/cooperatives`" qualified: server also exposes `GET /health` returning `{"status": "ok"}` — app.py:26-28

Notable non-changes (verified already aligned): all flat/nested route roles and filter sets, quorum ceiling math and equality, flip-tax formulas, allocation/residual formula with absorber tie-breaks, charge-supersede waiver cascade, termination cascade, no-show/auto-adjourn 24h rules, and the §3.6 fiscal-gate semantics (already fixed by Step 8).

## Pipeline Complete — 2026-08-13T21:52:00.000Z

All 9 steps done. Final tree: SCAFFOLD.yaml (98 endpoints, 16 entities, 12 state machines, 9 calculations; lint clean), SCAFFOLD_DIFFICULTY_DESIGN.yaml (18 instances), SCAFFOLD_CORNER_DESIGN.yaml (32 instances), test_helpers/ (9 modules), test_suite/ (68 tests in 7 files), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/ (~3,161 lines Flask, in-memory, 98/98 endpoints)}. Step 7 verification: 8/8 parallel rounds × 68/68 tests pass under per-test-server isolation.
