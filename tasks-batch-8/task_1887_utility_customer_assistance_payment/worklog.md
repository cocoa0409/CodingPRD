# Worklog — task_1887_utility_customer_assistance_payment

## Step 1: Create Task Directory — 2026-08-14T22:57:00.000Z

Directory `tasks/task_1887_utility_customer_assistance_payment/` and `workspace/` pre-created by pipeline invoker (per command args).

## Step 2: Generate Scaffold — 2026-08-14T23:30:00.000Z

Done. All three scaffold artifacts for task 1887 are written and lint-clean.

## Files written

| File | Lines |
|---|---|
| `/home/ubuntu/github/CodingPRD/tasks/task_1887_utility_customer_assistance_payment/SCAFFOLD.yaml` | 1367 |
| `/home/ubuntu/github/CodingPRD/tasks/task_1887_utility_customer_assistance_payment/SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1097 |
| `/home/ubuntu/github/CodingPRD/tasks/task_1887_utility_customer_assistance_payment/SCAFFOLD_CORNER_DESIGN.yaml` | 2050 |

Lint verdict (verbatim): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (55 endpoints, 11 entities, 18 difficulty instances, 57 corner instances, 514 calls scanned). Top-level key separation honored; no forbidden concurrency vocabulary; all 79 instance names unique; all `grounds:` references resolve.

## Scaffold overview

**Complexity profile**: Compliance/audit primary + quota/allocation secondary; layers: cascading side effects, dual-variant calculation, OCC, ops-run checkpoint. Flat topology (FK links, filtered-list reverse reachability), cyclic state machines, segregation-of-duties role model (application verifier != submitter), immediate consistency. Logical clock with pinned default `2026-08-01T00:00:00Z`.

**Entity model (11)**: CustomerAccount (parallel dimensions `service_status` × `protection_status`, OCC version parent), AssistanceApplication (provisional vs final benefit tier), AssistanceEnrollment (tier/discount lifecycle with lapse/recertify cycle), DeferredPaymentAgreement (snapshot ledger: covered = paid + forgiven + remaining), Payment (immutable waterfall event), ForgivenessCredit (posted/reversed), MedicalCertificate (half-open 30-day windows, 2-renewal cap), ShutoffOrder (SCHEDULED↔BLOCKED cycle), FundingSource (appropriation counters), FundAllocation (waterfall batches with pinned enrollment revalidation), AssistanceReferral (60-day expiry). 33 error codes across a 33-priority validation chain (auth → shape → existence → SoD → OCC → state → safety → referential → temporal → constraint → fiscal).

**Calculations (10)**: FPL-cross-multiplication tiering with ANNUALIZED_CURRENT_MONTH vs ANNUAL_GROSS variants; tiered DPA terms (max/round branches, final-installment remainder absorption); forgiveness accrual PROJECTED vs POSTED variants with per-credit rounding remainder; 7-bucket payment waterfall; inclusive delinquency thresholds; protection gate (medical > weather precedence, winter [Nov 1, Apr 1), 32F/95F inclusive boundaries); reconnection fee with pinned per-component rounding (3492 vs 3491 trap); fund waterfall selector (rank ASC, created_at tie-break, all-or-nothing); report aggregation; certificate window arithmetic.

**Difficulty design (§1.8, 18 instances)**: all nine rules × 2 differentiated instances — dual variants on different domains (income vs forgiveness), combinatorial modes (a) tiered down-payment vs (b) nested rounding, cycles on different entities (application docs loop, DPA default/reinstate loop), cascades of depth 4 (certificate-expiry sweep chain; payment→DPA-activation→order-cancel→reconnect chain), priority conflicts on different category pairs (state>safety; referential>fiscal), boundary precision on different metrics/endpoints (income==150% FPL at verify; 32F at sweep), cross-entity deps on different pairs (ShutoffOrder×MedicalCertificate; FundAllocation×AssistanceReferral), overlap with different interval semantics (half-open adjacency vs aggregate capacity-1), and compensating invariants on different quantities (fund pool; DPA arrearage ledger through BROKEN reversal). All numeric asserts are precomputed literals (e.g. 3492, 10834/10831, 4167×5+4165, 85500→95500).

**Corner design (§1.9, 57 instances: 53 active + 4 excluded-because stubs)**: entities (defaults, immutability, computed/system field handling), state machines (initial/terminal lockdown, block-unblock cycle, fund-close cascade, referral expiry boundary, recertify cycle), calculations (tier boundaries, waterfall order, rounding remainders, report, heat/winter windows), validations (priority ordering, SoD, notice/cure windows, docs gate, min-arrearage boundary, duplicates, capacity), endpoints (pagination, FK filtered lists, supersede reverse reachability), errors (envelope shape), RBAC (unauthenticated/unauthorized/ownership/positive customer payment), cross-cutting (two OCC stale-version tests, selector tie-break, sweep idempotency with no-version-bump, suspended-fund exclusion), consistency (immediate read-after-write).

## Step 3: Copy Shared Files — 2026-08-14T23:31:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1887_utility_customer_assistance_payment/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T23:42:00.000Z

PRD generation complete. Output: `/home/ubuntu/github/CodingPRD/tasks/task_1887_utility_customer_assistance_payment/workspace/PRD.md` — 329 lines. The withheld difficulty/corner design files were never opened; no other task directories were read.

## Section structure

- **§1 Introduction** — 2 paragraphs, business-context angle (regulatory tension of the care office → system scope)
- **§2 Global Specifications** (10 subsections): 2.1 RBAC (headers, 5 roles, Customer entity-backed identity vs 4 opaque staff identities), 2.2 API Response Structure (verbatim fixed block), 2.3 Pagination, 2.4 Program Clock & Date Semantics (startup default 2026-08-01T00:00:00Z, `to_iso8601`/`current_utc`), 2.5 Common Resource Properties & the Immutable Payment Record, 2.6 Money/Integer Cents/Rounding, 2.7 OCC on Account-Mutating Creates, 2.8 Request Validation Order & Identifier Resolution (9-stage global pipeline), 2.9 Account Versioning/Activity Stamping/Cascades, 2.10 Moratorium Gates & Order Synchronization
- **§3 Business Logic** (9 subsections, grouped by business process): 3.1 Accounts/Balances/Delinquency, 3.2 Applications & Income Eligibility, 3.3 Enrollment & Recertification, 3.4 DPA Terms/Default/Cure, 3.5 Payment Waterfall & Forgiveness Accrual, 3.6 Medical Certificates & Moratorium Protection, 3.7 Shutoff Orders/Execution/Reconnection, 3.8 Funding Sources/Allocation Waterfall/Reporting, 3.9 Referrals & the Nightly Sweep
- **§4 Endpoint Definitions** — 55 rows, 4 columns only; **§5 Error Code Catalogue** — 33 rows, 2 columns only

## Hard contract reports

- **Contract 1 (Field-Name Coverage): PASS** — entity fields 96/96 present; endpoint input tokens 47/47 present; path params 11/11 present (6 live inside §4's backticked path tokens). Verified mechanically with two passes (first pass caught a regex parity bug from the §2.2 fenced JSON block, not a PRD defect; second pass clean).
- **Contract 2 (Rule Coverage): PASS** — validation priority orderings expressed for the global pipeline (§2.8) and every multi-guard endpoint (verify: SoD→state→documents; DPA create: OCC→one-active→arrearage floor; shutoff create: 7-rule chain in priority order; reconnect, reinstate, disburse/release, allocate, activate, renew). Both OCC rules name write operation + `expected_account_version` + `ERR_STALE_ACCOUNT_VERSION`/412 with no race framing. All state transitions (incl. self-loop cert renewal, WEATHER→MEDICAL flip, Payment's immutability), all 10 calculations (cross-multiplication income tiers, pinned 6-step DPA terms, pinned per-component fee rounding, 7-bucket waterfall, half-open cert windows with adjacency rule, all-or-nothing fund waterfall), all cascades (credit reversals on BROKEN/CANCELLED, order auto-cancel, protection sync, stranded pledges on terminate), and all 33 error IDs appear in §2/§3 narrative. Two gaps found and patched during the walk: the literal `EXECUTED` state token, and explicit SoD on manual deny.
- **Contract 3 (§3 Path Purity): PASS** — 562 backticked tokens in §3, zero paths/methods/combos; endpoints referenced via state-pair framing, role+verb, or capability description.

## Deliberate information-scattering choices

- **Unit conversion as difficulty lever**: all cent constants rendered as exact dollar prose ($100.00 floor, $33.25 base fee, $75.00 deposit, $25.00/$50.00 down-payment minimums, full 8-row FPL guideline table + $5,500 adder in narrative).
- **Endpoint parameters split across subsections**: DPA creation's `installment_count`/`account_id` live in §3.4 while its `expected_account_version` contract lives in §2.7; payment inputs in §3.5 with its auto-cancel consequence cross-referenced from §3.7; sweep weather inputs introduced in §3.6's gate and completed in §3.9's stage list; `after_hours`/`reconnection_surcharge_applied` fold-in narrated in §3.7 while the surcharge is *computed* from constants also in §3.7 but the payment bucket that pays it down is §3.5.
- **Redundant reinforcement**: terminate-strands-pledges appears in both §3.3 and §3.8; protection-gate precedence stated in §2.10 and detailed in §3.6; kept-current-DPA protection stated in §3.4, §3.5, §3.7, and §3.9 from different angles.
- **Reconciliation of scaffold tension**: the account state machine's loose "auto-cancel on protection arose" was resolved to the sweep's pinned semantics (protection blocks/unblocks; only sub-$100 arrearage or a kept-current DPA cancels), stated consistently in §3.7 and §3.9.

## Step 5: Generate Unit Tests — 2026-08-15T00:05:00.000Z

Generation complete. All artifacts are written, compile cleanly, and pass every audit.

## File inventory (3,450 lines total)

**test_helpers/** (1,190 lines):
- `/home/ubuntu/github/CodingPRD/tasks/task_1887_utility_customer_assistance_payment/test_helpers/__init__.py` (24) — barrel export
- `.../test_helpers/types.py` (290) — 11 entity TypedDicts (Payment omits `version`/`updated_at` per PRD §2.5), 13 status/role enums
- `.../test_helpers/api_client.py` (183) — 53 endpoint methods covering the full PRD §4 routing table
- `.../test_helpers/api_errors.py` (80) — all 33 error IDs + HTTP map, registered with the framework at import
- `.../test_helpers/assertions.py` (160) — per-entity assertions, `assert_date_eq` (day-precision), `assert_dpa_ledger_invariants`, `assert_fund_conservation`, `assert_breakdown_sums_to`
- `.../test_helpers/factories.py` (100), `constants.py` (73 — FPL table, tier shares, fee/notice/grace constants, tier income presets), `test_users.py` (47 — shared constants + per-instance builders incl. entity-backed `make_customer_headers`), `fixtures.py` (233 — composite setups: verified applications, ACTIVE enrollments, activated DPAs, disconnected accounts, sweeps)

**test_suite/** (2,260 lines): `conftest.py` (35) + 11 test files — `test_01_accounts.py` (102), `test_02_applications.py` (304), `test_03_enrollments.py` (91), `test_04_payments.py` (125), `test_05_dpa.py` (430), `test_06_shutoff.py` (297), `test_07_protection_gate.py` (211), `test_08_medical_certificates.py` (103), `test_09_funding.py` (304), `test_10_reconnection.py` (71), `test_11_system_and_rbac.py` (187).

## Coverage mapping

**Queue A (Difficulty): 18/18 instances translated, exactly 2 tests each = 36 tests.** Every dual-variant, combinatorial, cyclic-state, cascade, priority-pair, boundary, cross-entity, overlap, and invariant instance is covered with literal expected values (e.g., fee 2328+1164=3492 pinned-rounding, DPA ledger 24500/10000/85500→95500, fund 60000→40000→100000 round-trip).

**Queue B (Corner): 56 of 57 non-stub instances translated = 56 tests.** The 4 `excluded_because:` stubs were not translated; all four cross-references verified to resolve to real difficulty instances.

**Skipped (1):** `Corner/entities/account_create_computed_field_input_rejected`. The PRD's §2.8 shape stage covers required fields, types, enum members, and ranges but never states that a client-supplied system field (`arrearage_balance_cents`) in a create payload must be rejected rather than ignored — two faithful PRD-only readers could ship either behavior, so it fails the unique-derivability condition. Gap left as a gap; no placeholder emitted.

## Self-check findings (all clean)

- All 21 files compile; `test_helpers` imports successfully against the installed framework; every name imported by the suite resolves; all 53 client methods exist.
- Every one of the 92 test docstrings ends with exactly one `Design:` line; all tags resolve to real instances in the source YAMLs (0 unresolved, 0 untagged, 0 dual-tagged).
- Queue A ≥2/instance and queue B ≥1/instance verified programmatically (only the intentional skip flags).
- All 154 quoted citation spans pass a strict verbatim check: every contiguous 8-word window appears literally in `PRD.md`.
- No `pytest.mark.skip`/`skipif`/`xfail` anywhere.

**Deliberate derivability choices:** date fields asserted at day precision (PRD pins calendar dates, not serialization format); `paid_at` asserted by `"2026-08-01T00:00:00"` prefix; allocation batch rows sorted by `allocation_sequence` before assertion (batch response row order is not PRD-pinned; the sequence field is); forgiveness credits matched by `installment_number` (same-timestamp list order not pinned). The DEFAULTED-DPA catch-up payment (instances `dpa_default_reinstate_cycle`, `reinstate_cure_window_expired`) was kept because the PRD's documented cure path is unreachable otherwise, making installment settlement of a DEFAULTED DPA uniquely derivable by internal consistency.

## Step 6: Generate Implementation — 2026-08-15T00:06:00.000Z

All 55 endpoints implemented and verified. Server killed; workspace clean.

## Summary

Complete Python + Flask implementation for task 1887 (Utility Customer Assistance & Payment Arrangement Program) written to `/home/ubuntu/github/CodingPRD/tasks/task_1887_utility_customer_assistance_payment/workspace/implementation/`.

**File inventory (2,846 lines total):**
- `start.sh` (10) — guarded install, `exec python3 app.py`
- `requirements.txt` (1) — flask>=3.0,<4.0
- `app.py` (43) — Flask entry, blueprint registration, envelope-mapped 400/404/405 handlers
- `db.py` (119) — empty in-memory dicts per entity, logical clock (default exactly `2026-08-01T00:00:00Z`, never wall clock), ISO-8601 3-fractional-digit formatters
- `errors.py` (68), `response.py` (46), `middleware.py` (37), `validate.py` (138), `serializers.py` (227)
- `routes/` — ops (31), accounts (129), applications (230), enrollments (110), dpas (144), payments (65), certificates (137), orders (163), funding (229), referrals (87)
- `services/` — common (162), tiers (42), dpa_terms (50), dpa_ops (106), waterfall (145), protection (61), reconnect (39), funds (95), sweep (132)

**Endpoints: 55/55 implemented** (matches scaffold §1.5 table exactly, including `_clock/set_current_utc` and `ops/daily-sweep`).

**Organization:**
- *State machines* live in route handlers (guard order: auth → role → ownership → shape → existence left-to-right → SoD → OCC → state → business) with side effects delegated to services; parallel `protection_status` dimension handled by `services/protection.py` with immediate SCHEDULED↔BLOCKED order sync and WEATHER→MEDICAL reason flip.
- *Calculations* isolated per service: integer cross-multiplication income tiers (`tiers.py`), pinned-order DPA terms with Fraction exact arithmetic (`dpa_terms.py`), forgiveness accrual with final-installment remainder keyed off actually-POSTED credits (`dpa_ops.py`), 7-bucket payment waterfall with whole-installment oldest-first settlement (`waterfall.py`), pinned per-component round-half-up reconnection fees (`reconnect.py` — w=30 example verified: 2328+1164), ranked all-or-nothing fund waterfall with counters recomputed from rows (`funds.py`), 8-stage pinned daily sweep with change-only version bumps (`sweep.py`).
- *Validation order* follows PRD §2.8 strictly; OCC (`expected_account_version` → `ERR_STALE_ACCOUNT_VERSION` 412) enforced only on application/DPA creation.

**Notable spec-resolution decisions** (both traced to explicit PRD prose): waterfall bucket 3 settles installments for DEFAULTED DPAs as well — otherwise the §3.4 cure cycle (`ACTIVE→DEFAULTED→ACTIVE` via reinstate with all due installments settled) is unreachable; failed reconnect attempts with `after_hours=true` persist the one-time surcharge fold-in (PRD: "exactly once, at which point that flag flips to true").

**Verified:** two self-authored suites (~95 assertions) pass on fresh boots — full lifecycle, fee math, moratorium gates, sweep tallies, OCC, waterfall splits, credit reversals, pagination/limits, and the error catalog.

**start.sh contract confirmed:** reads `$PORT` (default 10000 in `app.py`), binds `0.0.0.0`, runs in foreground via `exec`, dependency install guarded by `python3 -c "import flask"` so per-test-server reboots skip pip. No seeding anywhere — the store provably starts empty (every suite run began with a fresh process).

## Step 7: Run Tests and Iterate — 2026-08-15T00:15:00.000Z

All 8 rounds pass cleanly: 92/92 in every round. Exiting with the summary.

## Summary

- **Iterations run:** 2 (sweep 1: 3 deterministic failures in all 8 rounds; fixes applied; sweep 2: 92/92 passed in all 8 rounds).

- **Tests deleted:** none. All three failing tests traced to verbatim PRD sentences with uniquely derivable outcomes; all three failures were test-artifact bugs.

- **Fixes applied to `test_helpers/`:** none.

- **Fixes applied to `test_suite/`:**
  1. `/home/ubuntu/github/CodingPRD/tasks/task_1887_utility_customer_assistance_payment/test_suite/test_03_enrollments.py` — `test_enrollment_lapse_then_recertify_cycle`: expected `recert_due_on` changed from `"2028-08-01"` to `"2028-07-31"`. PRD §3.3 states verbatim "resets `recert_due_on` to the clock date plus 365 days"; clock 2027-08-01 + 365 days = 2028-07-31 because 2028 is a leap year (2028-02-29 falls in the window). The test had mis-translated "plus 365 days" as "+1 calendar year"; the implementation was arithmetically correct.
  2. `/home/ubuntu/github/CodingPRD/tasks/task_1887_utility_customer_assistance_payment/test_suite/test_05_dpa.py` — `test_occ_dpa_create_stale_version_rejected`: added missing module-level `ADMIN = TEST_USERS["admin_headers"]` (the file previously defined only `CSR`), fixing a `NameError`. ProgramAdmin is a PRD-sanctioned role for `GET /assistance/dpas` (PRD endpoint table: "List deferred payment agreements | CustomerServiceRep, ProgramAdmin"), matching the pattern already used in test_08.
  3. `/home/ubuntu/github/CodingPRD/tasks/task_1887_utility_customer_assistance_payment/test_suite/test_08_medical_certificates.py` — `test_renewal_limit_reached`: corrected the three `effective_to` expectations (renewal 1 → `"2026-09-30"`, renewal 2 → `"2026-10-30"`, unchanged → `"2026-10-30"`). PRD §3.6 states the certificate "is born `ACTIVE` with an `effective_to` exactly 30 days after `effective_from`" (2026-08-01 → 2026-08-31) and "each renewal extends `effective_to` by another 30 days"; the test's expectations had ignored the initial 30-day window. The implementation was correct.

- **Fixes applied to `implementation/`:** none — the implementation was PRD-faithful on all three rules.

## Step 8: Finalize PRD — 2026-08-15T00:20:00.000Z

Done. The diff contains exactly the two intended inline revisions, both confined to §3.3.

## Summary

**Line counts / delta:** PRD.md 329 lines; PRD_FINALIZED.md 329 lines — 0 lines, 0.0% delta (both edits are inline revisions within existing paragraphs; two sentences modified).

**Changes (both trace to step_7_diff item 1; items 2 and 3 required no edit):**
- §3.3 (activation paragraph) — revise — appended to "sets `recert_due_on` exactly 365 days later" the clause "— a fixed whole-day count added to the clock date, not a shift to the same calendar date one year out, so a 365-day span that crosses a February 29 lands one day before the calendar anniversary" — impl: `implementation/routes/enrollments.py:69` (with `implementation/db.py:42-43`, `add_days` = `timedelta(days=365)`).
- §3.3 (recertification paragraph) — revise — extended "resets `recert_due_on` to the clock date plus 365 days" with "under the same whole-day count (for example, 2027-08-01 plus 365 days is 2028-07-31, the span having crossed 2028-02-29)" — impl: `implementation/routes/enrollments.py:95`.

**No-edit verdicts:**
- step_7_diff item 2 (`test_05_dpa.py` missing `ADMIN` variable): pure test-scaffolding `NameError`. The PRD endpoint table already authorizes `ProgramAdmin` for `GET /assistance/dpas`, and impl `routes/dpas.py:25` (`LIST_ROLES = ["CustomerServiceRep", "ProgramAdmin"]`) matches. No PRD prose implicated.
- step_7_diff item 3 (`test_08_medical_certificates.py` renewal expectations): §3.6 is triply pinned — born with `effective_to` exactly 30 days after `effective_from`, renewals extend "by *another* 30 days", and "covers at most 90 days in total" arithmetically forecloses the test's reading (which would cap coverage at 30 days). Impl `routes/certificates.py:55,116` matches. The test simply failed to apply the first sentence; no faithful divergent reading exists.

**Pre-edit search log:**
- **Edit 1 (activation sentence).** (a) Subject: the 365-day `recert_due_on` rule at enrollment activation. (b) Paths enumerated: `routes/enrollments.py:69` (activation setter), `routes/enrollments.py:95` (recertify setter — same arithmetic, same subject), `routes/applications.py:194` (sets `recert_due_on` to None at creation), `services/sweep.py:53-55` (lapse comparison `today >= recert_due_on`), `serializers.py:79` (date rendering), `db.py:42-43` (the shared `add_days` helper), plus a repo-wide grep over all 13 date-arithmetic sites (`dpa_ops.py:24`, `waterfall.py:81`, `certificates.py:55,116`, `sweep.py:69,80,92,113`, `dpas.py:117`, `orders.py:70`, `common.py:88`) confirming every one is `timedelta(days=n)` and no `relativedelta`/`replace(year=...)` calendar-shift arithmetic exists anywhere. (c) Wording scoped explicitly to `recert_due_on` and phrased as description of the existing count rule, so it cannot misdescribe the 30-day certificate/installment windows, 15-day notice, 60-day referral expiry, or §3.8's fiscal-year extraction.
- **Edit 2 (recertify sentence — the actual Step 7 failure site).** (a) Subject: the same 365-day rule at recertification. (b) Same enumeration as Edit 1; the example arithmetic was verified independently (2027-08-01 + 365 whole days = 2028-07-31, matching both `timedelta` semantics and the step_7_diff narrative). (c) Used "under the same whole-day count" to cross-reference Edit 1 rather than restating the rule in a second formulation, eliminating any risk of the two clauses drifting apart; "Certification is annual" and §2.4's "recertification anniversaries" framing were left untouched, as both remain true as business framing and are now explicitly non-normative for the arithmetic.

File produced: `/home/ubuntu/github/CodingPRD/tasks/task_1887_utility_customer_assistance_payment/workspace/PRD_FINALIZED.md`.

## Step 9: Complete PRD — 2026-08-15T00:30:00.000Z

Step 9 complete. `/home/ubuntu/github/CodingPRD/tasks/task_1887_utility_customer_assistance_payment/workspace/PRD_COMPLETED.md` produced from `PRD_FINALIZED.md` (which existed) with a minimal in-paragraph patch.

**Source vs output:** PRD_FINALIZED.md 329 lines / 59,401 chars → PRD_COMPLETED.md 329 lines / 61,374 chars. Char-delta: **+1,973**, line-delta 0 (all edits inline, no new sections/paragraphs).

**Counts:** 13 ambiguity-pins, 1 mismatch-revision (14 changes total, delivered as 13 Edit operations; 11 diff hunks).

**Changes:**
- §2.3 — insert — ambiguity — invalid `limit`/`offset` (non-integer, limit outside 1–100, negative offset) and out-of-set filter values rejected with `ERR_INVALID_REQUEST` (400) — `implementation/validate.py:84-128`
- §2.3 — insert — ambiguity — list-sort ties on `created_at` broken by resource creation order, earliest first (normative under a frozen logical clock) — `implementation/validate.py:137-138`
- §2.4 — insert — ambiguity — date-valued fields (`arrearage_since`, `activated_on`, `recert_due_on`, `lapsed_on`, `first_installment_due_on`, `defaulted_on`, `effective_from`, `effective_to`, `scheduled_date`, `initiated_on`, `completed_on`) render as midnight-UTC ISO 8601 timestamps — `implementation/serializers.py:16-17`, `implementation/db.py:33-39`
- §2.8 stage 4 — revise — ambiguity — extended integer-range enumeration (deposit/income ≥ 0; charge/payment/allocation `amount_cents` strictly positive) and pinned that undeclared body fields are ignored — `implementation/validate.py:37-81`, `implementation/routes/accounts.py:38,98`, `implementation/routes/applications.py:57-58`, `implementation/routes/funding.py:145`
- §3.1 — revise — ambiguity — new-account initial state pinned: reconnection fee fields all zero, `reconnection_surcharge_applied` false, `last_activity_at` stamped at creation — `implementation/routes/accounts.py:50-57`
- §3.1 — revise — ambiguity — charge `amount_cents` pinned as strictly positive integer — `implementation/routes/accounts.py:98`
- §3.2 — revise — ambiguity — both income figures pinned as non-negative integers — `implementation/routes/applications.py:57-58`
- §3.2 — revise — ambiguity — deny `reason_code` pinned to closed enum `INCOME_OVER_LIMIT|DOCS_INSUFFICIENT|OTHER` (was "for example") — `implementation/routes/applications.py:20,205-206`
- §3.3 — insert — ambiguity — recertify with a `new_application_id` failing VERIFIED/same-account/different-id rejected with `ERR_INVALID_STATE` (409) — `implementation/routes/enrollments.py:86-91`
- §3.4 — revise — ambiguity — reinstate's third guard (due installment unsettled → `ERR_INVALID_STATE` 409, evaluated after the cure-window check) pinned — `implementation/routes/dpas.py:120-122`
- §3.5 — revise — **mismatch** — waterfall bucket 3 serves whole installments of an `ACTIVE` **or `DEFAULTED`** agreement (PRD said `ACTIVE` only; DEFAULTED path makes the §3.4 reinstatement cure reachable) — `implementation/services/waterfall.py:66-67`
- §3.5 — insert — ambiguity — bucket-4 extra arrearage payment capped at the agreement's `remaining_balance_cents` — `implementation/services/waterfall.py:93-95`
- §3.8 — revise — ambiguity — allocation request `amount_cents` pinned as strictly positive integer — `implementation/routes/funding.py:145`
- §3.8 — insert — ambiguity — allocation batch create responds 201 with `response_type: array`, rows in fill order, and meta `limit`/`total_count` = rows created, `offset` 0, `has_more` false — `implementation/routes/funding.py:160-161`

Everything else in the implementation (all 40 endpoints, role tables, validation-chain orders, tier/DPA/fee/waterfall formulas, sweep stage order and tallies, error catalogue, response envelopes) was already uniquely pinned by PRD_FINALIZED.md and verified against the code with no change needed.
