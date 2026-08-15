# Worklog — task_1977_rural_water_district_billing_association

## Step 1: Create task directory — 2026-08-15T04:19:00.000Z

Directory tasks/task_1977_rural_water_district_billing_association/ and workspace/ created by pipeline launcher (pre-existing when orchestrator started).

## Step 2: Generate scaffold — 2026-08-15T05:02:00.000Z

All checks pass. The scaffold is complete and lint-clean.

## Summary

Generated the three scaffold artifacts for task 1977 (Rural Water District Billing & Association Operations) at maximum difficulty, without consulting any sibling task:

**Files written:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1977_rural_water_district_billing_association/SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1977_rural_water_district_billing_association/SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_1977_rural_water_district_billing_association/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`

**Counts:**
- Entities: 16 (District, ServiceArea, AnnexationPetition, Member, TapConnection, MeterReading, MasterMeterReading, RateSchedule, BillingCycle, Invoice, Payment, ReserveEntry, BoilOrder, NotificationReceipt, ComplianceSample, BoardResolution)
- State machines: 10 (parallel-dimension Invoice machine, cyclic AnnexationPetition resubmission and Member ACTIVE↔SUSPENDED loops, fork/join BoardResolution, guarded TapConnection disconnect)
- Calculations: 8 (incl. dual-variant pairs: provisional vs final water loss, estimated vs actual reading billing; pinned round-per-tier-then-sum tiered pricing; ceil-division reserve deposit chain; waterfall allocation with pinned absorb order)
- Validations: 27 (priority-ordered; segregation-of-duties at p3, boil-order moratorium safety at p6 outranking fiscal disconnect eligibility at p17)
- Endpoints: 81 (incl. `/_clock/set_current_utc` with the mandated 2026-08-01T00:00:00Z default, and reverse-reachability GETs for every FK)
- Errors: 46 (every one referenced by a validation or transition)
- Roles: 5 (SystemAdmin, BillingClerk, Treasurer, BoardDirector, FieldOperator) — segregation_of_duties role model; all opaque identity
- Concurrency rules: 2 true OCC races on `District.version` (cycle close, reserve-withdrawal proposal), both wired to `expected_district_version` inputs and version-bump side effects
- §1.8 difficulty instances: 18 non-stub (2 per rule × 9 rules), all with structured setup chains, literal-pinned payloads, pre-computed numeric asserts (e.g. U=12500 → 5700 vs naive 5350; exact-floor withdrawal 900 ≥ 900)
- §1.9 corner instances: 38 non-stub + 2 `excluded_because` stubs (both citations resolve to §1.8 instances)

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (863 calls scanned, 0 violations; zero unbound `${var}` placeholders; all instance names unique across both design files.)

**Key design notes:** The linter's FK reverse-reachability check (f) required `api_prefix: ""` plus 24 additional flat/sub-resource GET endpoints so every `FK ->` field is reachable; forbidden-vocabulary scan is clean; all OCC version payloads use `${var}` captures, never literals.

## Step 3: Copy shared files — 2026-08-15T05:03:00.000Z

Copied ./INSTRUCTION.md to tasks/task_1977_rural_water_district_billing_association/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-15T05:08:00.000Z

All three contracts pass. `QUORUM` is a scaffold constant name (`QUORUM_FOR=3`, `QUORUM_AGAINST=3`) — the PRD expresses the rule in prose ("reaches 3", "votes_against reaches 3 with votes_against at least equal to votes_for"), which satisfies the no-pseudocode rule; the constant names themselves are not field names, so Contract 1 doesn't require them. The quorum rule is fully expressed.

The PRD is complete and verified. Final summary:

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1977_rural_water_district_billing_association/workspace/PRD.md` — **328 lines**.

### Section list
- §1. Introduction (2 paragraphs — business context + system scope)
- §2. Global Specifications & System-Wide Principles
  - 2.1 User and Role-Based Access Control (5 roles, opaque identities, segregation-of-duties)
  - 2.2 API Response Structure (**emitted verbatim** from `section-2.2-response-structure.md`, byte-for-byte verified)
  - 2.3 Pagination (`limit` 10/1/100, `offset` 0, `created_at` ascending, meta fields)
  - 2.4 Common Resource Properties and the Logical Clock (UUID/timestamps/`version`; the four `common_fields: false` entities named explicitly; logical clock pinned at 2026-08-01T00:00:00Z)
  - 2.5 Money, Precision, and Rounding (integer cents, 3-decimal half-up loss percentages, pinned round-per-tier-then-sum)
  - 2.6 Optimistic Concurrency Control (both `concurrency_rules`: cycle close and RESERVE_WITHDRAWAL proposal, `expected_district_version` → `ERR_STALE_VERSION`/412)
  - 2.7 Nested Resource Retrieval and Validation Ordering (left-to-right 404 family, full priority-order narrative, reverse-reachability reads)
  - 2.8 Hierarchical Consistency and Cascade Discipline
- §3. Business Logic & Workflows — 11 subsections organized by domain lifecycle (district setup → membership/taps → billing cycle → charge arithmetic → water loss → delinquency/disconnect → payments → reserve covenant → board governance → annexation → boil orders)
- §4. Endpoint Definitions — 81-row table, 4 columns only (Method / Path / Description / Authorized Roles)
- §5. Error Code Catalogue — 46-row table, 2 columns only (Error ID / HTTP Status)

### Hard-contract reports
- **Contract 1 (Field-Name Coverage):** 86 required identifiers (all `entities[].fields[].name` + all endpoint `input`/`query_params`/`path_params` + `current_utc`), 86 present in backticks, 0 missing → **PASS** (after repairing `billing_status`, `collection_status`, `district_id`)
- **Contract 2 (Rule Coverage):** all 9 state machines' 42 transition state-pairs named in prose; all 8 calculations rendered as precise prose (tiered ceil-division, pinned `invoice_total` max-floor, provisional/final loss with FINAL_OFF-replacement and chronological ordering, ÷120 ceiling monthly deposit, 110% rate covenant, 75% withdrawal floor, credit-absorbs-first waterfall, $250/20% fee split); all 27 validations matchable to their `error_id` in §2/§3; both OCC rules fully expressed (endpoint + field + error + status, no race framing); validation priority ordering stated explicitly; side-effect cascades (member delinquency counters, SUSPENDED cycling, district version increments, annexation→ServiceArea creation, sample→order cascades) all narrated → **PASS**
- **Contract 3 (§3 Path Purity):** 382 backticked tokens scanned in §3, 0 path tokens, 0 bare HTTP methods, 0 method+path combos → **PASS**

### Coverage audit
- **Entities:** all 16 covered in prose, including computed fields (`reserve_deficit_cents`, `covenant_status`, `boil_order_active`, `cycle_index`, `days_past_due`, `billed_total_cents`, `resulting_balance_cents`, etc.) and defaults (`member_class=RESIDENTIAL`, `meter_size=FIVE_EIGHTS_INCH`, `reading_type=ACTUAL`).
- **State machines:** all 9 (RateSchedule, BillingCycle, Invoice dual-dimension, TapConnection, Member, AnnexationPetition incl. REJECTED→SUBMITTED resubmission, BoardResolution fork, BoilOrder, ComplianceSample, ServiceArea) with preconditions paired to error IDs.
- **Calculations:** all 8, with constants embedded in prose (NOTICE 10 days, DISCONNECT 45 days inclusive, quorum 3/3, floor 0.75 → "75 percent", ratio 1.1 → "110 percent", fee floor 25,000 cents, fee pct one-fifth, 24-hour notify window, 72-hour sampling window).
- **Validations:** all 27, including priority ordering as an explicit ordered narrative in §2.7.
- **Endpoints:** all 81 in §4, including all 26 reverse-reachability reads; query filters (`membership_status`, `billing_status`, etc.) intentionally left out of the table per the minimal-table rule.
- **Errors:** all 46 in §5 and each mentioned with its trigger in §2/§3.
- **Roles:** all 5 with opaque-identity prose; segregation-of-duties rule (bill-vs-collect, proposer-vs-deciding-vote) stated.

### Deliberate omissions (per skill rules, not gaps)
- §4 table carries no request/response bodies or side effects (minimal-table rule); query-parameter filters are reachable only via §3 narrative + envelope.
- §5 carries no trigger conditions (2-column rule).
- Scaffold constant *names* (`QUORUM_FOR`, `NOTICE_DAY_THRESHOLD`, `WITHDRAWAL_FLOOR_RATIO`, `FEASIBILITY_FEE_FLOOR_CENTS`, etc.) are translated to natural-language values per the no-pseudocode rule; they are not field names and are not Contract-1 required.
- The withheld design files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened.

## Step 5: Generate unit tests — 2026-08-15T05:45:00.000Z

Generation complete for task_1977_rural_water_district_billing_association.

## Summary

**Tests emitted: 71 total** — Queue A (Difficulty): 34 tests across 17 instances (≥2 each); Queue B (Corner): 37 tests across 36 non-stub instances (≥1 each).

**Instances skipped (3), with reasons:**
1. `Difficulty/priority_pair_validation_conflict/sampling_window_vs_notification_completeness_priority` — asserts sample *creation* on an IN_EFFECT order fails `ERR_ORDER_NOT_SAMPLING`, but PRD §3.11 attaches `ERR_ORDER_NOT_SAMPLING` only to record-result; no PRD sentence states a SAMPLING precondition for `POST /compliance-samples`, so the outcome is not uniquely derivable (a faithful implementer would return `ERR_SAMPLE_WINDOW_VIOLATION` for the out-of-window payload).
2. `Corner/endpoints/filtered_list_invoices_by_collection_status` — the `collection_status` query filter appears only in the scaffold endpoint row; PRD §2.3 names only `limit`/`offset` and §4 lists no filter params, so filter behavior has no verbatim PRD coverage.
3. `Corner/rbac/segregation_of_duties_same_user_bill_then_close` — PRD §2.1 segregation covers only bill↔payment and proposer↔deciding-vote; a bill↔close prohibition appears nowhere in the PRD.

**Deliberately dropped sub-assertions (documented gaps, tests still emitted for the derivable core):** (a) `sample_present_cascade_depth3`'s claim that `boil_order_active` stays true and disconnect is moratorium-blocked after `VIOLATION_ESCALATED` — PRD §3.6 limits the moratorium to `IN_EFFECT` orders, so only the PRESENT→escalation→version hops are asserted; (b) `payment_reverse_conserves_invoice_outstanding`'s credit-absorb leg (scaffold's `applied_cents == 4850` contradicts PRD §3.7's tender-only `applied_cents` definition) — reversal conservation is tested in a credit-free scenario where PRD uniquely determines the outcome; (c) `reserve_monthly_deposit_ceil_rounding`'s `covenant_status == RESERVE_DEFICIENT` assert — PRD never defines "projected annual revenue," so the rate-coverage leg is underivable; (d) three recipes (D8, D13, LB) assumed disconnect succeeds while a fresh unpaid CURRENT invoice exists, contradicting PRD §3.6's "every unpaid invoice on the tap must be in `DISCONNECT_ELIGIBLE` status" — fixtures repaired by paying the fresh-cycle invoice before disconnect, preserving each instance's claim.

**test_helpers/ (9 files):** `__init__.py` (barrel), `types.py` (18 entity TypedDicts + 16 enums; ledger entities omit `updated_at`/`version`), `api_client.py` (all 64 endpoints), `api_errors.py` (49 error IDs + HTTP map registered with framework), `assertions.py`, `factories.py`, `constants.py` (thresholds, S1 schedule, cycle windows, clock instants), `test_users.py` (opaque role headers + distinct board-voter builders), `fixtures.py` (composite chains: adopted schedule, installed tap, billed invoice, disconnect-eligible/disconnected scenarios, close-with-OCC, boil-order helpers).

**test_suite/ (11 files):** `conftest.py` plus `test_01_api_envelope_and_auth.py`, `test_02_district_and_membership.py`, `test_03_rates_taps_and_install.py`, `test_04_meter_readings_and_cycle_windows.py`, `test_05_invoices_and_tiered_pricing.py`, `test_06_water_loss_and_close.py`, `test_07_payments_credits_reversals.py`, `test_08_delinquency_disconnect_reconnect.py`, `test_09_governance_reserve_annexation.py`, `test_10_boil_orders_and_samples.py`.

**Stage 2 self-audit verdict: PASS** — 71/71 tests tagged, zero untagged, zero dual-tagged, zero tags pointing at non-existent instances or at `excluded_because:` stubs (both stub pointers verified to resolve); all 17 surviving difficulty instances have exactly 2 tests; all 36 surviving corner instances have ≥1; all 96 quoted citation fragments grep-verbatim against PRD.md; no skip/xfail markers; no scaffold references in generated code; all imports resolve and pytest collects 71 tests cleanly.

## Step 6: Generate implementation — 2026-08-15T05:45:00.000Z

Implementation complete. All files live under `/home/ubuntu/github/CodingPRD/tasks/task_1977_rural_water_district_billing_association/workspace/implementation/`.

## File list

- `start.sh` — executable launcher; guarded dep install (`if ! python3 -c "import flask"`), then `exec python3 app.py`
- `requirements.txt` — `flask>=3.0,<4.0`
- `app.py` — Flask entry point, ApiError/404/405 handlers, blueprint registration, `app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))`
- `db.py` — in-memory stores + logical clock (default `2026-08-01T00:00:00Z`, never wall-clock), ISO-8601 3-fractional-digit formatting, insertion sequencing
- `errors.py`, `response.py` — `ApiError` carrier; envelope helpers (`meta.api_request_id` `req_*`, `api_request_timestamp`, `response_type`, `data`; list meta `limit`/`offset`/`total_count`/`has_more`; defaults 10/1–100/0)
- `middleware.py` — `X-User-ID`/`X-User-Role` auth (400), per-endpoint role gate (403), body/type validation (400), district-scoped lookups (404 family)
- `services.py` — calculations: tiered usage (ceil-per-tier-then-sum), invoice total (pinned max-order), provisional/final water loss (Decimal half-up, 3 dp, FINAL_OFF-replacement semantics), delinquency escalation (10/45-day inclusive thresholds, one rung per cascade in pinned 45→10→past-due order), reserve covenant (ceil(annual/120) monthly deposit, exact-rational 75% withdrawal floor), annexation fee split (half-up 20% leg vs 25000 floor), waterfall (credit absorbs before tender)
- `routes/core.py` — clock, districts, service-areas, members (13 routes)
- `routes/taps.py` — taps lifecycle (8 routes)
- `routes/billing.py` — billing-cycles (incl. OCC-guarded close), meter/master readings, invoices, payments+reverse, reserve-entries (17 routes)
- `routes/governance.py` — rate-schedules, board-resolutions + record-vote with quorum/SoD/atomic covenant check (6 routes)
- `routes/petitions.py` — annexation petitions (6 routes)
- `routes/safety.py` — boil orders, notifications, sampling, compliance samples (8 routes)
- `routes/reverse.py` — bare-id and nested reverse-reachability reads (23 routes)

## Endpoint count

**81 routes**, matching the SCAFFOLD endpoint table exactly (58 district-rooted + 23 reverse-reachability).

## Entity stores (all in-memory dicts in `db.py`, empty at boot)

`districts`, `service_areas`, `members`, `taps`, `readings` (MeterReading), `master_readings`, `rate_schedules`, `billing_cycles`, `invoices`, `payments`, `reserve_entries`, `boil_orders`, `notifications`, `samples` (ComplianceSample), `resolutions`, `petitions`. No seeding, no disk/JSON/SQLite persistence anywhere; module-init code creates no entities.

## start.sh contract

Verified by direct execution: honors `$PORT` (tested 19341/19342), binds `0.0.0.0` (reachable via external interface IP), runs in the foreground via `exec` (server is the direct child of the script), boots in ~2s (well under 60s), and starts with an empty store at the default logical clock.

## Verification

A 53-assertion end-to-end smoke suite passed 0 failures, covering: reserve baseline, rate-schedule sanity (422), resolution proposal/adoption version bumps (+1 propose, +2 adopt-with-subject-event), duplicate-vote vs proposer-deciding-vote SoD, tap fee overpay→credit, auto 0-reading on install, duplicate/regression readings, ceil-per-tier billing, payment waterfall absorb-first, bill/collect SoD, OCC 412 + master-reading 409 at close, delinquency aging with frozen `days_past_due` at disconnect, disconnect eligibility gates, member suspend/reactivate, reconnect fee on next invoice, FINAL_OFF replacement in final loss, boil-order notify→sample→lift flow with window enforcement, annexation fee split, withdrawal covenant breach (atomic — vote not recorded), auth/role/404 errors, and the list envelope.

One judgment call worth noting: the PRD mentions `RATE_COVENANT_BREACH` via "projected annual revenue" without defining a formula anywhere; the implementation derives `covenant_status` from the fully-specified reserve deficit side (`RESERVE_DEFICIENT`/`IN_COMPLIANCE`) rather than inventing an underivable revenue projection.

## Step 7: Run tests and iterate — 2026-08-15T06:30:00.000Z

**Result: clean 8-round parallel sweep — 71/71 passed in every round (568/568 test executions).**

### Iterations run
3 sweeps. Sweep 1 baseline: 42/71 in all 8 rounds (fully deterministic — 29 failures, zero flakiness). Sweep 2 after the four primary fixes: 71/71 × 8. Sweep 3 after one final PRD-fidelity fix in payment recording: 71/71 × 8 (exit).

### Tests deleted (none fully deleted; one truncated per STEP 1c partial-coverage rule)
- `test_03_rates_taps_and_install.py::test_abandon_blocked_with_billing_history_allowed_otherwise` → truncated to its covered half and renamed `test_abandon_allowed_without_billing_history`. The removed assertion demanded `ERR_TAP_HAS_BILLING_HISTORY` when abandoning an **INSTALLED** tap with an invoice. **Pattern: ERROR PRECEDENCE SILENCE.** PRD §3.2 scopes the named error to never-in-service taps ("A tap that *was never put into service* may be abandoned … only while no invoice exists for it; otherwise `ERR_TAP_HAS_BILLING_HISTORY`"), while §2.7 pins state-legality checks (including the generic invalid-state family, whose error id the PRD never names) ahead of business rules. Two faithful readers diverge (state-first with an invented id vs. business-error-always), and the scaffold rule that drove generation (`tap_abandon_with_billing_history_rejected`, which models no from-state gate) is exactly what the PRD prose does not pin. The retained half asserts the verbatim-covered `FEE_PENDING → ABANDONED` success path.

### Fixes applied to `test_helpers/`
- `test_helpers/fixtures.py::create_district` — parameter renamed `name=` → `district_name=`. Every call site passes `district_name=`, which collided with the explicit `district_name=name` kwarg through `**overrides` (TypeError blocked 19 tests before any assertion ran).
- `test_helpers/fixtures.py::setup_billed_invoice` — an early `due_date_utc` override now clamps `period_end_utc` down to the due date. The old window (period 08-01→09-01, due 08-10) violated PRD §3.3's "due_date_utc at or after period_end_utc", so the PRD-faithful implementation correctly rejected it with `ERR_CYCLE_WINDOW_INVALID` (7 delinquency/payment tests). Fixture bug, per the triage hint.

### Fixes applied to `test_suite/`
- `test_03_rates_taps_and_install.py` — the truncation above, plus removal of the newly-unused `setup_billed_invoice` import.

### Fixes applied to `implementation/`
- `workspace/implementation/routes/core.py::area_serviceable` — a body-referenced `service_area_id` that is nonexistent or belongs to a different district now yields `ERR_AREA_NOT_SERVICEABLE` (422) per PRD §3.2 verbatim ("The referenced area must belong to the same district and be in `ACTIVE` or `ANNEXED_IN` status, or the application is rejected with `ERR_AREA_NOT_SERVICEABLE`"), instead of `ERR_AREA_NOT_FOUND` (the §2.7 404 family governs *path* identifiers, not body references).
- `workspace/implementation/routes/core.py::terminate_member` — the non-ABANDONED-tap conjunct of the termination gate now raises `ERR_OPEN_INVOICES_EXIST` (409) instead of `ERR_INVALID_STATE`; PRD §3.2 attaches that error to the whole compound condition ("only when every tap is `ABANDONED` or none exist and no invoice remains in `ISSUED` or `PARTIALLY_PAID` status — otherwise `ERR_OPEN_INVOICES_EXIST`"), and the target resource (an ACTIVE member) has no state violation.
- `workspace/implementation/routes/billing.py::create_payment` + `reverse_payment` — `applied_cents` now records the tender portion only (PRD §3.7: "the portion applied is the smaller of `amount_cents` and the remaining outstanding, recorded as the payment's `applied_cents`"); the credit absorb grows only the invoice's applied total, and reversal debits both legs (`applied_cents + _absorb_cents`) back off the invoice. Latent deviation found in audit — no current test exercises pre-existing credit, and behavior is unchanged when absorb = 0.

### Per-sweep record (subagent-appended iteration notes)

8-round parallel stability sweeps (`--isolation per-test-server`), union-of-failures diagnosis per round.

**Sweep 1 baseline:** 42/71 in all 8 rounds (deterministic; 29 failures in 3 clusters).

**Sweep 2:** 71/71 × 8 rounds. **Sweep 3 (post-payment-fidelity change):** 71/71 × 8 rounds. Exit condition met.

## Step 8: Finalize PRD — 2026-08-15T06:09:00.000Z

Done. The final diff contains exactly the two intended in-place edits.

## Exit summary

**Line counts / delta:** `PRD.md` 327 lines → `PRD_FINALIZED.md` 327 lines; **0.0% delta** (2 lines revised in place, no insertions or deletions).

### Changes (one bullet per edit)

- **§3.2 — revise** — Tap-abandon error precedence pinned: `ERR_TAP_HAS_BILLING_HISTORY` now scoped to taps already in an abandonable from-state (`FEE_PENDING`/`PAID`); abandonment from any other status is a state-legality violation per §2.7 ordering and surfaces `ERR_INVALID_STATE` (HTTP 409) *before* the billing-history check — `implementation/routes/taps.py:212-217`
- **§3.7 — revise** — Reversal amounts pinned: reversal debits the payment's full invoice-side application (`applied_cents` tender portion **plus** any credit-absorb leg) off the invoice, claws back only the tender overpayment from the member's `credit_balance_cents`, and does **not** restore the absorbed pre-existing credit — `implementation/routes/billing.py:475,488-489,422-423`

### Step 7 items deliberately left verbatim (impl fixed to match PRD; no PRD silence)

- `area_serviceable` — PRD §3.2 already verbatim-pins `ERR_AREA_NOT_SERVICEABLE` for a referenced area failing to belong to the district (nonexistence included) at both application and approval (`core.py:131-137,150,195`).
- `terminate_member` — PRD §3.2 already attaches `ERR_OPEN_INVOICES_EXIST` to the whole compound gate ("…otherwise"), matching both conjuncts (`core.py:208-214`).
- `test_helpers/fixtures.py` fixes (`create_district` kwarg rename; `setup_billed_invoice` due-date clamp) — pure fixture bugs; PRD §3.3 already pins `due_date_utc` at/after `period_end_utc`. No behavioral content for the PRD.

### Per-edit pre-edit search log

**Edit 1 (§3.2 abandon):**
- (a) Subject: validation order and error ids on the tap-abandon transition.
- (b) Paths enumerated: `routes/taps.py::abandon_tap` (207-220, sole abandon path); all 11 `ERR_INVALID_STATE` raise sites via grep (`taps.py:85,108,146,191,213`; `core.py:121,194`; `safety.py:110,178`; `petitions.py:76`; `billing.py:376`) confirming `ERR_INVALID_STATE` is the impl's generic invalid-state id; `core.py::terminate_member` (reads `ABANDONED`, transition set unchanged); §2.7 ordering (state-legality before business rules).
- (c) Adjustment: named the concrete id `ERR_INVALID_STATE` locally (PRD's §2.7 names the family but no id; the step-7 divergence was "state-first with an invented id vs. business-error-always", so the id had to be pinned for behavioral equivalence) but scoped the naming to the abandon site only — no global claim about other state-guard sites, which Step 7 never flagged.

**Edit 2 (§3.7 reversal):**
- (a) Subject: composition of the reversal debit and credit-restoration semantics.
- (b) Paths enumerated: `billing.py::create_payment` (399-424: absorb draw, `applied_cents`=tender only, overpay→credit); `billing.py::reverse_payment` (465-493: invoice debited `applied_cents + _absorb_cents`, member debited `_overpay_cents` only, absorb never re-credited); `billing.py::_update_invoice_after_payment` (429-442); `services.py::ser_payment` (84-85); plus all other `credit_balance_cents`/`amount_paid_cents` touches (`taps.py:91` tap-fee excess, `core.py:215-219` termination forfeiture, `close_cycle:222-237` streak logic) — none interact with reversal wording.
- (c) Adjustment: replaced the ambiguous "the applied amount" (misreadable as tender-only `applied_cents` after that field's narrowed definition) with "the tender portion recorded as `applied_cents` plus any credit-absorb amount that grew the invoice's applied total", and added the parenthetical "(the absorbed pre-existing credit is not restored)" to pin the non-restoration; left "recomputes the invoice's billing status from what remains" untouched since impl recomputes billing status only and no path contradicts it.

File produced: `/home/ubuntu/github/CodingPRD/tasks/task_1977_rural_water_district_billing_association/workspace/PRD_FINALIZED.md`

## Step 9: Complete PRD — 2026-08-15T06:23:00.000Z

Done. `PRD_COMPLETED.md` written at `/home/ubuntu/github/CodingPRD/tasks/task_1977_rural_water_district_billing_association/workspace/PRD_COMPLETED.md`.

## Summary

**Source**: `PRD_FINALIZED.md` (existed; copied as base). Line counts: 327 → 331; char delta: +5,612 (50,671 → 56,283).

**Counts**: 27 ambiguity-pins, 10 mismatch-revisions (37 total behavioral changes across 18 edited passages).

### Changes

- **§2.3** — insert — ambiguity — pagination clamping/defaults (non-integer → default, limit clamped to [1,100], offset floored at 0), `has_more` = offset + page-length < total_count, `created_at` ties broken by insertion order, and the exact-match query filters each list endpoint accepts — `implementation/response.py:44-65`, filter blocks in every `routes/*.py` list handler.
- **§2.4** — revise — mismatch — "Three resource kinds" → "Four" (the ledger list has four entries) — `implementation/services.py:33-38`.
- **§2.4** — insert — ambiguity — clock-set accepts any valid instant (no comparison to current reading) and returns the supplied string verbatim as `current_utc` — `implementation/routes/core.py:20-30`.
- **§2.5** — revise — mismatch — dropped the "rate-coverage ratio" from the exact-rational sentence (impl computes only the withdrawal floor) — `implementation/services.py:143-148` (no coverage arithmetic anywhere).
- **§2.6** — insert — ambiguity — the proposal OCC guard applies to every resolution type when `expected_district_version` is supplied — `implementation/routes/governance.py:108-111`.
- **§2.7** — revise — mismatch — segregation-of-duties moved after path-existence in the validation ordering (payment collection needs the invoice's cycle; record-vote checks it after state and duplicate-vote) — `implementation/routes/billing.py:392-397`, `implementation/routes/governance.py:198-210`.
- **§3.1** — insert — ambiguity — rate adoption repoints `active_rate_schedule_id` regardless of the target's prior status; only a `DRAFT` target moves to `ADOPTED` — `implementation/routes/governance.py:147-159`.
- **§3.2** — insert — ambiguity — tap-fee quote defaults to 0 for a member class absent from `tap_fee_schedule`; tender is zero-or-more; `tap_fee_paid_cents` capped at the quoted fee; collecting on a non-`FEE_PENDING` tap → `ERR_INVALID_STATE` (409) — `implementation/routes/taps.py:37,78-97`.
- **§3.2** — insert — ambiguity — auto-created install reading targets the most recently opened `OPEN` cycle — `implementation/routes/taps.py:122-136`.
- **§3.2** — insert — ambiguity — each forfeited credit posts its own `ANNUAL_TRUE_UP` entry at next close — `implementation/routes/core.py:215-219`, `implementation/routes/billing.py:215-217`.
- **§3.3** — insert — ambiguity — only `CLOSED` cycles constrain the new cycle's window; cycle's loss percentages are null until billed/closed — `implementation/routes/billing.py:64-85`.
- **§3.3** — insert — ambiguity — regression baseline is the tap's most recently accepted reading across all cycles; readings accepted regardless of cycle status — `implementation/routes/billing.py:31-36,257-260`.
- **§3.3** — revise — mismatch — duplicate rule: a `FINAL_OFF` may follow the tap's regular reading for the cycle (replacing it); a second `FINAL_OFF`, or any regular reading once one exists, is `ERR_DUPLICATE_READING` — `implementation/routes/billing.py:261-271`.
- **§3.3** — revise — mismatch — master readings are not unique at posting; close rejects anything but exactly one — `implementation/routes/billing.py:303-318,206-209`.
- **§3.3** — insert — ambiguity — readings-completeness requires a non-`FINAL_OFF` reading per `INSTALLED`/`RECONNECTED` tap — `implementation/routes/billing.py:39-44,116-120`.
- **§3.3** — revise — mismatch — billing creates one invoice per billed tap (not "per tapped member") — `implementation/routes/billing.py:141-179`.
- **§3.3** — revise — mismatch — close walks only members with a non-`VOID` invoice this cycle; streak resets only when all such invoices reached `PAID` at a logical-clock instant ≤ `due_date_utc`; others keep their streak — `implementation/routes/billing.py:222-237`.
- **§3.4** — revise — mismatch — "one per tapped member" → one per billed tap; billing reads the non-`FINAL_OFF` reading when present, else the `FINAL_OFF` — `implementation/routes/billing.py:145,153`.
- **§3.4** — insert — ambiguity — a disconnected tap's invoice carries the reading's `usage_gallons` but zero usage charge and zero reconnect fee, so total equals `base_minimum_cents` — `implementation/routes/billing.py:152-157`.
- **§3.5** — revise — mismatch — provisional master side is the most recently posted master reading (not "the cycle's single value") — `implementation/services.py:211-219`.
- **§3.5** — revise — mismatch — deleted the "revenue view of the loss" sentence; impl derives/exposes no such figure — `implementation/services.py:222-232` (returns only pct and sold).
- **§3.6** — revise — mismatch — `days_past_due` also freezes when the invoice reaches `PAID`, and a reversal that un-pays unfreezes it unless `DISCONNECTED` — `implementation/routes/billing.py:437-439,481-486`.
- **§3.6** — insert — ambiguity — escalation advances at most one rung per evaluation — `implementation/services.py:237-257` (elif chain).
- **§3.6** — insert — ambiguity — issue-notice on a non-qualifying invoice → `ERR_INVALID_STATE` (409) — `implementation/routes/billing.py:363-377`.
- **§3.7** — insert — ambiguity — payments accepted against invoices in any billing status (tender on a paid invoice flows entirely to credit); paying member need not own the invoice — `implementation/routes/billing.py:384-411`.
- **§3.7** — insert — ambiguity — reversal does not re-evaluate collection status (a cured invoice stays `CURRENT`) — `implementation/routes/billing.py:472-487`.
- **§3.8** — revise — mismatch — `covenant_status` reduced to two states (`RESERVE_DEFICIENT` / `IN_COMPLIANCE`); removed the `RATE_COVENANT_BREACH` tier and coverage-ratio definition (impl never computes them — confirmed by grep) — `implementation/services.py:143-147`.
- **§3.8** — insert — ambiguity — covenant floor evaluated at the deciding vote; a breaching deciding vote is rejected before any tally is recorded — `implementation/routes/governance.py:213-217`.
- **§3.9** — insert — ambiguity — vote values are `FOR`/`AGAINST`; withdrawal/loan-amendment payload shape validated as `ERR_INVALID_REQUEST` (400) — `implementation/routes/governance.py:88-97,195`.
- **§3.9** — revise — mismatch — district version increments twice on adoption of `RATE_ADOPTION`/`ANNEXATION_RATIFICATION` (subject action + adoption), once for `RESERVE_WITHDRAWAL`/`LOAN_AMENDMENT`, never on failure — `implementation/routes/governance.py:159,184,224-236`.
- **§3.10** — insert — ambiguity — recommend with a non-`ACTIVE` parent area → `ERR_INVALID_STATE` (409); withdrawal legal only from `FEASIBILITY_REVIEW`; ratification acts only while the petition is `APPROVED_PENDING_VOTE`; new area is named after `petitioner_name`; `feasibility_fee_cents`/`refund_cents` null until settled — `implementation/routes/petitions.py:35-36,74-76,87`, `implementation/routes/governance.py:168-184`.
- **§3.11** — revise — mismatch — `boil_order_active` is derived (true iff any order `IN_EFFECT`); it clears when the last `IN_EFFECT` order leaves that status, including at sampling start — `implementation/routes/safety.py:25-29,120`.
- **§3.11** — insert — ambiguity — issuance not blocked by an existing `IN_EFFECT` order; notification receipts recordable regardless of order status; sample collection not gated on order status; double result recording → `ERR_INVALID_STATE` (409); lift rule is the two most recently resulted samples both `ABSENT` — `implementation/routes/safety.py:34-51,68-91,128-148,177-198`.
- **§5** — insert — ambiguity — added catalogue rows `ERR_INVALID_STATE` (409) and `ERR_NOT_FOUND` (404), plus a sentence pinning unmatched-path/unmatched-method behavior (404/405) — `implementation/app.py:27-41`.
