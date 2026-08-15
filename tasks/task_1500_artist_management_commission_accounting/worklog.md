# Worklog — task_1500_artist_management_commission_accounting

## Step 1: Create Task Directory — 2026-08-13T14:09:00.000Z

Task directory `tasks/task_1500_artist_management_commission_accounting/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher. Step 1 treated as DONE; no index scan performed, no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-13T16:08:53.000Z

Scaffold generation complete. All three files are written and the lint verdict is clean.

### What was generated

**`/home/ubuntu/github/CodingPRD/tasks/task_1500_artist_management_commission_accounting/`** — three files (~381 KB total), generated purely from the scenario + skill spec (no sibling tasks inspected).

#### SCAFFOLD.yaml (§1.0–§1.7)
- **Complexity profile**: primary archetype `ledger_reconciliation`, secondary `multi_party_negotiation`; layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, scheduled_actions; flat topology, cyclic state-machine shape, segregation-of-duties role model, immediate consistency.
- **15 entities**: Artist, Agreement (self-referential supersede chain + sunset window fields), CommissionRateSchedule (half-open effective-dated windows), IncomeEvent (self-referential adjustments, rate snapshot pinning), Advance, Expense, ApprovalRequest (polymorphic target), Opportunity, Engagement (buffered windows), Option, TeamMember, Statement (self-referential carry chain + rate snapshot), StatementLine (append-only, `common_fields: false`), Dispute, Audit.
- **14 state machines** with cycles (Opportunity NEGOTIATING⇄UNDER_EVALUATION on a 10% counter-offer band, Statement ISSUED⇄DISPUTED amendment cycle, Audit reopen cycle capped at 2), auto-transitions via a logical clock (default fixed at `2026-08-01T00:00:00Z`, forward-only), and spelled-out hop-by-hop cascades.
- **3 OCC concurrency rules** (all true create-with-supersede/stale-update races): `POST /agreements` on Artist.version, `PATCH /agreements/{id}` on Agreement.version, `POST /opportunities/{id}/counter-offer` on Opportunity.version — each endpoint takes `expected_*_version` and bumps the parent version.
- **12 calculations**, all with pinned constants/precision: sunset-aware commission rate resolution (per-income-type sunset months + deal-must-be-confirmed-in-term gate), commission with GROSS vs NET_OF_EXPENSES variants, FIFO vs PRO_RATA recoupment waterfall, statement generation with ACCRUAL vs CASH variants + pinned carry-chain evaluation order + $500 disbursement threshold, expense approval routing tiers, weighted opportunity scoring, three distinct interval-overlap semantics (half-open rates / buffered engagements / closed statement periods), audit cost allocation (5% exact-rational ratio + $25k floor), option window check.
- **14 ordered validations** (auth → scope → shape → existence → state → OCC → SoD → temporal → referential → constraint → fiscal), **83 endpoints**, **39 error codes**, **6 roles** with layered identity semantics (FirmAdmin/Auditor opaque; Agent/BusinessManager/Publicist entity-backed by TeamMember with artist scoping; Artist entity-backed).

#### SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8) — 23 instances
dual_variant_calc 3, combinatorial_formula 3 (modes a/b/c), non_linear_state_machine 2, transitive_cascade 2 (settle→advance→RECOUPED→artist; exercise→CONFIRMED→release HOLD→withdraw opportunity), priority_pair_validation_conflict 2 (state-vs-fiscal, temporal-vs-constraint), boundary_precision_check 3 (money threshold, 5% ratio, inclusive time bounds), cross_entity_state_dependency 3, resource_temporal_overlap 3 (three distinct interval semantics), compensating_invariant 2 (advance principal partition; disbursed+carry_out==net_payable). Every assert is a precomputed literal (e.g., 94118 gross → 14118 commission → 80000 cash share; FIFO 65000 vs PRO_RATA 58182).

#### SCAFFOLD_CORNER_DESIGN.yaml (§1.9) — 64 instances (55 active + 9 excluded_because stubs)
Sections: entities 5, state_machines 6, calculations 5 (incl. the three sunset classifications), validations 27, endpoints 3, rbac 4, cross_cutting_layers 4 (OCC positives/negatives, fixed default clock + monotonicity), consistency_model 1, errors 9 stubs. All 39 error codes have at least one live trigger.

#### Verification
- `scaffold_lint.py`: **VERDICT: clean lint** — 729 calls scanned across §1.8+§1.9, all conform to §1.5; all §1.1 FKs reverse-reachable; exit 0.
- Stub citations all resolve to real §1.8 instance names; instance names unique across both files (87 total); no forbidden race vocabulary.

Notable design repairs made during replay auditing: agreement resolution changed to "greatest term_start_date ≤ recognition_date" so POST_TERM_EXEMPT is reachable; dispute-window error re-mapped to ACKNOWLEDGED/FINALIZED statements (the deemed-acceptance sweep made the naive version unreachable); all fixtures made forward-only against the fixed default clock.

## Step 3: Copy Shared Files — 2026-08-13T16:09:30.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1500_artist_management_commission_accounting/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-13T16:45:00.000Z

PRD generated and all three hard contracts pass. Summary below.

### Output

**File:** `/home/ubuntu/github/CodingPRD/tasks/task_1500_artist_management_commission_accounting/workspace/PRD.md` — 377 lines, ends at §5 (no audit footer).

### Section list

- **§1. Introduction** — 2 paragraphs (business-pain-point angle, not the "This document outlines..." template)
- **§2. Global Specifications** (9 subsections): 2.1 RBAC, 2.2 API Response Structure (byte-identical verbatim block — verified against `section-2.2-response-structure.md`), 2.3 Pagination, 2.4 Common Resource Properties, 2.5 Money/Rates/Rounding, 2.6 The Logical Clock, 2.7 Validation Order and Error Precedence, 2.8 Optimistic Concurrency Control, 2.9 Cascading Mutations and the Artist Aggregate Ledger
- **§3. Business Logic** (9 subsections, grouped by business process): 3.1 Roster & Teams, 3.2 Agreements/Rate Schedules/Sunset, 3.3 Opportunity Pipeline, 3.4 Calendar/Engagements/Options, 3.5 Income Reporting/Verification/Settlement, 3.6 Advances & Recoupment Waterfall, 3.7 Expenses & Approval Routing, 3.8 Statement Production, 3.9 Disputes/Escalation/Audits
- **§4. Endpoint Definitions** — 83-row table, 4 columns only (Method, Path, Description, Authorized Role(s))
- **§5. Error Code Catalogue** — 39-row table, 2 columns only

### Coverage notes

- **Entities:** all 15 covered; `StatementLine`'s `common_fields: false` explicitly called out (only `id` + `created_at`, no `updated_at`/`version`). All defaults stated (`home_currency` USD, `touring_commission_base` GROSS, `recoupment_policy` FIFO, `kind` ORIGINAL, `recoup_pct_bps` 10000, `travel_buffer_hours` 24, `authority_expense_cap_cents` 100000, `revision_number` 1, etc.).
- **State machines:** all 13 covered with every transition's from/to, preconditions paired to error IDs, and side-effect cascades (supersede chain, settle waterfall hops, convert/exercise/confirm hold-release cascades, issue sweep, amend hops, POSTED latch, deemed acceptance).
- **Calculations:** all 12 rendered as precise natural language (reconstruction-tested wording; both worked examples for `FIFO`/`PRO_RATA` and `GROSS`/`NET_OF_EXPENSES` included; constants embedded with cent values plus dollar glosses — $1,000/$10,000 tiers, $100,000 approval threshold, $500 disbursement floor, $25,000 firm-bearing floor, 5% ratio with exact-rational comparison, 365-day windows, 30-day dispute window, 0.5/0.3/0.2 weights, 70/40 recommendation thresholds).
- **Validations:** all 14 priorities stated as an explicit ordered list in §2.7; every `applies_to` scope enumerated (e.g., SoD on exactly approve/reject/verify; `ERR_ARTIST_ARCHIVED` blocking all 8 mutation types with the disputes/audits exemption).
- **Endpoints:** all 83 in §4; side effects narrated in §3; 201-vs-200 rule paragraph above the table (including convert/exercise/escalate returning 201 with the created resource).
- **Errors:** all 39 in §5; each also mentioned with its trigger condition in §2/§3 prose.
- **Roles:** all 6 with exact spelling; `identity:` translated per role — Agent/BusinessManager/Publicist entity-backed via `TeamMember` (member_role match + artist chain), Artist entity-backed via `Artist.id`, FirmAdmin/Auditor opaque.

### Contract reports

```
Field coverage check:
- entities[].fields + endpoints input/query/path identifiers: 139 required, 139 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] priority ordering: 14 checked, 14 expressed, 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (endpoint + expected_<parent>_version + error_id + 412), 0 missing
- state_machines[].transitions: all expressed including sibling branches, 0 missing
- calculations[]: 12 checked, 12 fully expressed (no pseudocode/operators/fuzzy words), 0 missing
- validations[] conditions: 14 matchable to error_ids in prose, 0 missing
- endpoints[].side_effects / applies_to: all expressed, 0 missing
- entities[].fields[] structured content (defaults/initials/types): reconstructible, 0 missing
- sibling-branch symmetry: FIFO/PRO_RATA, ACCRUAL/CASH, GROSS/NET_OF_EXPENSES, decline/withdraw/expire triplets, SUNSET/CLOSED branches all rendered with equal density
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 720
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

### Scaffold-to-prose translation decisions

1. **§2 subsection design** — domain-derived titles (Logical Clock, Money/Rates/Rounding, Validation Order, Artist Aggregate Ledger) instead of generic "System Integrity" templates; artist lifetime aggregates defined once in §2.9 and referenced from §3 workflows.
2. **§3 grouping** — business-process timeline (roster → agreements → pipeline → calendar → money in → money out → statements → disputes) rather than per-entity or per-role.
3. **Unit handling** — scaffold cent constants kept exact in cents with dollar glosses ("10000000 cents ($100,000)") so test-target values survive verbatim; the skill's unit-conversion suggestion was applied only as a gloss, never replacing the constant.
4. **Sunset arithmetic** — agreement-level window (`sunset_start_date`/`sunset_end_date`, max over schedules) narrated in §3.2; the per-income-type sunset test (schedule's own `sunset_months`, `confirmed_at` date-part deal-in-term check) narrated separately at verify time in §3.5, preserving the two distinct computations.
5. **Worked examples** — the scaffold's own numeric examples (FIFO 65000 / PRO_RATA 58182; GROSS 30000 / NET 25500) retained as prose sentences to pin evaluation order; no numbers taken from the difficulty/corner design files (never opened).
6. **§2.2** — emitted byte-identical from `section-2.2-response-structure.md` (verified by substring match), including `req_RANDOMALPHANUM123456` and empty `"data": { }`.

## Step 6: Generate Implementation — 2026-08-13T17:20:00.000Z

Implementation complete. Summary:

### File list
`/home/ubuntu/github/CodingPRD/tasks/task_1500_artist_management_commission_accounting/workspace/implementation/`
- `start.sh` — guarded launcher (`pip install` only if flask missing; `exec python3 app.py`)
- `requirements.txt`, `app.py` (Flask app factory, error handlers, blueprint registration, `0.0.0.0:$PORT`)
- `db.py` (in-memory store, 15 collections, empty at boot), `errors.py` (all 38 error IDs with exact HTTP statuses), `response.py` (`meta`/`response_type`/`data` envelope, pagination meta), `util.py` (UUIDs, 3-fractional-digit timestamps, logical clock defaulting to 2026-08-01T00:00:00Z, calendrical `add_months`, exact-integer `round_half_up`), `validate.py` (body shape / reference checks), `middleware.py` (auth priorities 1–4)
- `routes/`: one module per resource group (artists, agreements, rate_schedules, income_events, advances, expenses, approval_requests, opportunities, engagements, options, team_members, statements, disputes, audits, clock) plus `helpers.py` (list pagination, scoping, serialization)
- `services/`: `core.py` (record lifecycle, artist aggregate recompute, sunset windows, buffered-overlap cascade), `calculations.py` (rate resolution, commission, FIFO/PRO_RATA waterfall, statement generation, approval routing, evaluation scoring, audit cost allocation), `sweep.py` (clock sweep)

### Architecture & subsystem coverage
- **State machines**: all 14 entities implemented per scaffold §1.2, including POSTED-latch settle semantics (POSTED stays POSTED, recoup flows to next statement), dispute-driven statement DISPUTED↔ISSUED with compensation revert on withdraw, and the amend path appending ADJUSTMENT lines + revision bump + fresh 30-day window.
- **Calculations**: per-event round_half_up commissions (exact integer arithmetic, never re-derived at statement level); NET_OF_EXPENSES variant subtracting APPROVED/REIMBURSED engagement expenses with floor at 0 (verified 200000/30000/1500bps → 25500); FIFO and PRO_RATA waterfalls (floor shares, remainder to LAST advance; verified scaffold's exact worked example numbers); statement generation in the pinned 7-step evaluation order with the 50000-cent disbursement threshold and carry invariant; opportunity evaluation (365-day trailing avg, 0.5/0.3/0.2 weights, round at final step only, 70/40 thresholds with >= semantics); audit cost allocation as exact rational (`underpayment*100 >= base*5`, infinite ratio for non-positive base, 2500000 floor).
- **OCC**: `expected_artist_version` (POST /agreements), `expected_agreement_version` (PATCH /agreements/{id}), `expected_opportunity_version` (counter-offer); checked at priority 9, 412 with the scaffold's exact error IDs.
- **Cascades**: artist archive ends team members; agreement activation supersedes the prior ACTIVE (opens its sunset window, records `prior_agreement_id`, updates `current_agreement_id`, bumps artist version); confirm/convert/exercise release overlapping buffered HOLDs and withdraw their open opportunities (cancelling pending approvals); settle drives advance RECOUPED flips, artist recompute, and linked-engagement SETTLED; issue sweep posts income events, reimburses expenses, pins `recoup_statement_id`.
- **Validation ordering**: auth (headers → role list → artist scoping → team status) → body shape → path existence → body FK references → state → OCC → SoD → temporal → cross-entity → overlap/uniqueness → money limits, per PRD §2.7.
- **RBAC**: TeamMember entity-backed identity for Agent/BusinessManager/Publicist (role must match `member_role`, artist chain scoping, ACTIVE-only), Artist self-scope, opaque FirmAdmin/Auditor.

### Smoke checks run
Server booted via `bash start.sh` on ports 18911/18912/18913 (fresh process each time, empty store confirmed). ~100 endpoint probes all passing: envelope shape, pagination meta, full money pipeline (report→verify→advance→settle waterfall→statement generate/issue→dispute→resolve→amend→acknowledge→disburse), both waterfall variants against the scaffold's worked numbers, NET_OF_EXPENSES vs GROSS, SUNSET rate after clock sweep (sunset_start/end dates 2027-01-01/2027-06-30), POST_TERM_EXEMPT, 10% band boundary (exactly 10% stays, over loops back), carry chain below threshold, closed-interval period overlap (touching boundary counts), ERR_PRIOR_STATEMENT_OPEN, deemed acceptance + ERR_DISPUTE_WINDOW_CLOSED, audit lifecycle with reopen cap (3rd → 409), audit rights surviving artist archiving, OCC 412s, SoD, rate-schedule overlap/adjacency, clock regression rejection.

### PRD interpretation decisions
- **Read-endpoint existence vs scoping**: GET-by-id checks path existence (404) before artist scoping (403); creates check body scoping early since no path target exists yet.
- **`_swept_*` transient keys** on statements hold the generation sweep set until issue; stripped from serialized output via the `public()` filter.
- **Option exercise engagement** gets `counterparty_name: ""` (Option entity has no counterparty field; PRD doesn't specify one for the born engagement).
- **PATCH /artists same-status write** is treated as a field-update no-op rather than an invalid transition.
- **Audit window check** uses `issued_at < clock - 365d` for closure (inclusive boundary keeps exactly-365-days-old statements auditable per "inclusive" in the scaffold).
- The two apparent smoke failures in the audit test were arithmetic errors in my throwaway test script (50000/900000 = 5.55% ≥ 5% → FIRM is correct); verified the boundary directly (44999→ARTIST, 45000→FIRM).

## Step 5: Generate Unit Tests — 2026-08-13T17:55:00.000Z

Generation complete. Summary of what was produced and verified:

### test_helpers/ (9 files)
All under `/home/ubuntu/github/CodingPRD/tasks/task_1500_artist_management_commission_accounting/test_helpers/`:
- `types.py` — 16 entity TypedDicts + 20 status/role enums; `StatementLine` correctly carries only `id`/`created_at` (no `updated_at`/`version`)
- `api_client.py` — `ApiClient(GenericApiClient)` with 87 methods covering every endpoint incl. `/_clock/set_current_utc`
- `api_errors.py` — full 39-error catalog + HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions plus domain invariants (`assert_advance_partition`, `assert_statement_conservation`)
- `factories.py` — payload factories, input fields only
- `constants.py` — PRD thresholds (50000 disbursement, 100000/1000000 routing tiers, 10000000 artist-approval, 2500000 audit floor, 365-day windows)
- `test_users.py` — shared constants for opaque roles; `make_*_headers` per-instance builders for entity-backed roles (Agent/BusinessManager/Publicist → TeamMember.id, Artist → Artist.id)
- `fixtures.py` — tiered composites: `setup_artist_team()` (artist+agreement+rates+team with threaded identity headers), report/verify/settle chains, approval-walk helper, statement/dispute/audit/clock helpers
- `__init__.py` — barrel export

### test_suite/ (10 files)
`conftest.py` + `test_01_artist_roster_and_rbac.py`, `test_02_agreements_rates_and_occ.py`, `test_03_income_verification_and_settlement.py`, `test_04_advances_recoupment.py`, `test_05_expenses_and_approvals.py`, `test_06_opportunity_pipeline.py`, `test_07_engagements_and_options.py`, `test_08_statements.py`, `test_09_disputes_audits_and_clock.py`

**Total: 100 tests** (pytest collection verified clean).

### Queue A coverage (difficulty): 23/23 instances, 46 tests (exactly 2 each)
No skips. Each instance got a failure-path/variant test plus a control-or-second-effect test (e.g. `approve_state_beats_fiscal_authority` got the dual-failure test plus a state-only control with sufficient cap).

### Queue B coverage (corner): 54/55 non-stub instances, 54 tests
- **Skipped (1):** `Corner/entities/income_event_create_ignores_computed_field_input_rejected` — fails the PRD-first filter twice: (1) no PRD sentence states that unknown body fields are rejected, so two faithful readers could ship reject-vs-ignore variants (not uniquely derivable); (2) the recipe's trigger uses a FirmAdmin caller on an Agent/BusinessManager-only endpoint, so the uniquely-derivable outcome would be `ERR_FORBIDDEN_FOR_ROLE`, not the asserted `ERR_INVALID_REQUEST`. Gap left as a gap.
- **9 `excluded_because:` stubs not translated**; all 9 `difficulty_instance` cross-references verified to resolve to real §1.8 instances.
- One instance note: `audit_reopen_limit_two`'s secondary assert (`cost_bearer == ARTIST`) contradicts the PRD rule on its own data (empty statement → base 0 → ratio +∞ → FIRM); the generated test keeps only the PRD-derivable reopen-limit assertions.

### Stage 2 self-audit result
- Every test ends its docstring with exactly one `Design: Difficulty/<rule>/<name>` or `Design: Corner/<section>/<name>` line, resolving to a real instance (0 untagged, 0 dual-tagged, 0 dangling).
- All 150 quoted PRD citation spans survive literal whitespace-normalized grep of `workspace/PRD.md` (0 failures after fixing 15 elision-style quotes).
- No `pytest.mark.skip`/`skipif`/`xfail` anywhere; no "scaffold" wording in generated code (helper renamed `setup_artist_team`); all files compile and import against the installed framework.

## Step 7: Test Iteration (8-round stability sweeps) — 2026-08-13T18:05:00.000Z

Iteration 1 sweep: 8/8 rounds at 99/100; union of failures = 1 test
(`test_sunset_linked_engagement_must_be_confirmed_in_term`, failed all 8 rounds,
deterministic: got IN_TERM, expected SUNSET).

Diagnosis (STEP 1–3): PRD 3.5 verbatim ("The agreement's effective end is its
`termination_date` when the agreement is `TERMINATED`...") covers the rule; the
test is faithful. Implementation bug, two latent defects on the same path in
`services/calculations.py::resolve_commission`:
1. Effective end keyed on current status `TERMINATED`; after the clock sweep
   moved the agreement TERMINATED → SUNSET the check fell through to
   `term_end_date`, so post-termination income verified as IN_TERM. Fixed to key
   on the persisted `termination_date` (stamped at termination, never cleared),
   consistent with PRD 3.2's terminated-agreement sunset window.
2. Missing `parse_datetime` import (NameError on the sunset + linked-engagement
   branch) — unmasked once fix 1 made the branch reachable.

No tests deleted; no test_helpers changes.

Iteration 2 sweep: 8/8 rounds at 100/100 — stable, done.

## Step 7: Run Tests and Iterate — 2026-08-13T18:12:00.000Z

### Summary

**Iterations run: 2** (each a full 8-round parallel sweep, 100 tests/round, per-test-server isolation)

**Result: all 8 rounds pass 100/100** — clean exit.

#### Diagnosis (iteration 1)
Union of failing tests across all 8 rounds: exactly one, deterministic (failed all 8):
- `test_03_income_verification_and_settlement.py::TestSunsetRates::test_sunset_linked_engagement_must_be_confirmed_in_term` — got `term_relation == "IN_TERM"`, expected `"SUNSET"`.

STEP 1: PRD verbatim-covers the rule (PRD §3.5: *"The agreement's effective end is its `termination_date` when the agreement is `TERMINATED`, otherwise its `term_end_date`… Only when both conditions hold does the event take `term_relation` `SUNSET`… otherwise it is `POST_TERM_EXEMPT`"*), and unique derivability holds when read together with §3.2 (a terminated agreement's sunset window is keyed to `termination_date`, and SUNSET remains a commissionable posture). STEP 2: test setup, request, and assertion are all PRD-faithful. STEP 3: implementation bug.

#### Tests deleted
None.

#### Fixes applied to `test_helpers/`
None.

#### Fixes applied to `implementation/`
Both in `/home/ubuntu/github/CodingPRD/tasks/task_1500_artist_management_commission_accounting/workspace/implementation/services/calculations.py`, function `resolve_commission`:

1. **Effective-end keyed on transient status instead of the persisted fact** — the code used `agreement["status"] == "TERMINATED"` to choose `termination_date` over `term_end_date`. Once the clock sweep advanced the agreement `TERMINATED → SUNSET`, the check fell through to `term_end_date` (2027-12-31), so income recognized after termination verified as `IN_TERM` instead of running the sunset test. Fixed to key on the presence of the recorded `termination_date` (stamped at termination, never cleared), which is the only reading consistent with §3.2's terminated-agreement sunset window.
2. **Missing `parse_datetime` import** — the sunset + `linked_engagement_id` branch called `parse_datetime(...)` without importing it from `util`; latent NameError that was unreachable until fix 1 made the branch live. Added to the import list.

Verified live against a manually booted server (both branches of the test: confirmed-in-term → `SUNSET` @750bps = 15000; confirmed-after-end → `POST_TERM_EXEMPT` @0), then confirmed by the second 8-round sweep with zero failures and zero flakiness.

## Step 8: Finalize PRD — 2026-08-13T18:20:00.000Z

Done. `PRD_FINALIZED.md` is written at `/home/ubuntu/github/CodingPRD/tasks/task_1500_artist_management_commission_accounting/workspace/PRD_FINALIZED.md`.

### Summary

**Line counts / %-delta:** PRD.md 377 lines, PRD_FINALIZED.md 377 lines — 0% line-count delta (one sentence revised in place within §3.5's verification paragraph; no sections added or removed).

**Changes (one total):**
- §3.5 — revise — "The agreement's effective end is its `termination_date` when the agreement is `TERMINATED`, otherwise its `term_end_date`" → "its recorded `termination_date` whenever one is present — termination stamps `termination_date` and nothing ever clears it, so it still governs after the agreement has moved on from `TERMINATED` to `SUNSET` — and otherwise its `term_end_date`" — `implementation/services/calculations.py:65-68` (field writes: `implementation/routes/agreements.py:52,183`; persistence through sweep: `implementation/services/sweep.py:33-44`).

**Fix 2 from the diff (missing `parse_datetime` import) required no PRD edit:** it is a pure code bug (latent NameError) in a branch whose behavior §3.5 already pins verbatim ("the linked engagement's `confirmed_at` date-part is on or before the effective end"). No PRD silence or mismatch.

**Per-edit pre-edit search log:**
- **Edit 1 (the only edit):**
  - (a) Subject: the effective-end anchor (`termination_date` vs `term_end_date`) in commission rate resolution at verification, feeding the IN_TERM boundary, the per-type sunset end, and the deal-in-term `confirmed_at` comparison.
  - (b) Impl paths enumerated and read/grepped: `services/calculations.py:53-95` (`resolve_commission`, selection at :65-68, downstream uses :71/:75/:83); sole callsite `routes/income_events.py:160` gated by `COMMISSIONABLE_POSTURES` at :156; `routes/agreements.py:52` (field born `None`), `:173-190` (stamped at terminate, `set_sunset_window` fed day-after), `:79-134` (PATCH never writes `termination_date` — DRAFT edits term dates/policies only, ACTIVE extends `term_end_date` only); `services/sweep.py:19-53` (never reads or clears `termination_date`; posture transitions key on `term_end_date`/stored `sunset_end_date`); `services/core.py:86-95` (`set_sunset_window` — stored window fields, separate concept); full-repo greps for `termination_date`, `term_end_date`, `sunset_start_date`, `sunset_end_date`, `TERMINATED`, `resolve_commission`, `term_relation`, `confirmed_at` confirming no other status-keyed choice exists.
  - (c) Wording adjustment: keyed the rule on the recorded field's presence rather than current status and stated the never-cleared persistence explicitly, so the sentence is exact for every enumerated posture — TERMINATED and SUNSET-after-termination anchor on `termination_date`; ACTIVE/EXPIRED/SUPERSEDED (field always `None`) anchor on `term_end_date`; CLOSED never reaches the code (verification gate rejects it). The sentence says nothing about `sunset_start_date`/`sunset_end_date`, leaving §3.2's window prose and §2.6's sweep prose untouched, and the rest of the §3.5 paragraph (sunset test, deal-in-term, rates) is verbatim.

## Step 9: Complete PRD — 2026-08-13T18:55:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1500_artist_management_commission_accounting/workspace/PRD_COMPLETED.md` produced as a minimal patch over `PRD_FINALIZED.md`, pinned to `implementation/`.

**Size delta:** PRD_FINALIZED.md 377 lines / 68,050 chars → PRD_COMPLETED.md 378 lines / 72,715 chars (+1 line, +4,665 chars; 24 changed hunks, no new sections).

**Counts:** 18 ambiguity-pin edits, 6 mismatch-revision edits (24 hunks total).

**Mismatch revisions** (PRD described behavior impl does not exhibit):
- §2.6 + §3.1 — revise — mismatch — clock sweep ends only `ACTIVE` team members; `SUSPENDED` members survive a passed `window_end_date` — `implementation/services/sweep.py:81-86`
- §2.7 item 5 — revise — mismatch — blanket "window end later than start" replaced with per-endpoint ordering, since team-member windows allow equality (`window_end >= window_start`) — `implementation/routes/team_members.py:30-31`
- §2.8 (+ companion phrasing in §3.2, §3.3) — revise — mismatch — all three expected-version fields are optional, checked only when supplied, not required — `implementation/routes/agreements.py:39-45,85-98`, `implementation/routes/opportunities.py:129-134`
- §3.1 — revise — mismatch — archived-artist blocked-creation list drops "agreements": impl allows DRAFT agreement creation for archived artists; the gate is at activation — `implementation/routes/agreements.py:28-61` (no archived check) vs `income_events.py:81`, `expenses.py:40`, `opportunities.py:55`, `engagements.py:47`, `options.py:53`, `advances.py:30`, `statements.py:49`
- §3.2 — revise — mismatch — ACTIVE edit carrying no `term_end_date` → `ERR_INVALID_STATE`, a non-later `term_end_date` → `ERR_INVALID_REQUEST`, other fields ignored, and no-change edits do not increment `version` (old text claimed every edit increments) — `implementation/routes/agreements.py:100-133`
- §3.5 — revise — mismatch — both REPORTED and VERIFIED voids increment the artist's `version` (old prose only mentioned it for VERIFIED) — `implementation/routes/income_events.py:218-220`
- §3.8 — insert — mismatch — statement-generation gate order pinned to impl's actual order (archived gate before future-period gate; overlap before prior-statement-open), overriding §2.7 numbering — `implementation/routes/statements.py:46-78`
- §3.9 — revise — mismatch — dispute resolve takes `outcome` of `UPHELD`/`REJECTED` (recorded as `RESOLVED_UPHELD`/`RESOLVED_REJECTED`), and the awarded-amount check fires after the state precondition — `implementation/routes/disputes.py:24,91-100`

**Ambiguity pins** (PRD silent; inserted what impl does):
- §2.1 — unresolvable/mismatched team-member identity → `ERR_ARTIST_ACCESS_DENIED` — `implementation/middleware.py:43-58,76-85`
- §2.2 — unmatched paths/methods → `ERR_NOT_FOUND` 404 in the standard envelope — `implementation/app.py:30-36`
- §2.3 — non-integer/out-of-range `limit`/`offset` → `ERR_INVALID_REQUEST`; list sort ties broken by `id` ascending — `implementation/routes/helpers.py:27-48,71`
- §2.6 — logical-clock-stamped fields (`confirmed_at`, `issued_at`, `dispute_window_ends_at`) render at whole-second precision; `created_at`/`updated_at` record wall-clock time — `implementation/util.py:18-21,43-45`
- §2.6 — one agreement may increment several sweep counts in a single advance (e.g. ACTIVE→EXPIRED→CLOSED) — `implementation/services/sweep.py:19-53`
- §2.7 — create endpoints extract the body scoping key (`artist_id`; `agreement_id` resolved for rate-schedule creation) before header/role checks; single-resource reads check path existence before scoping/team-status — `implementation/routes/helpers.py:78-93`, `implementation/routes/rate_schedules.py:40-45`
- §2.9 — completed the artist version-bump side-effect list (agreement create/terminate, income reporting/voiding, advance issuance, sweep expiry clearing `current_agreement_id`) — `implementation/services/core.py:29-67`
- §3.1 — artist PATCH: unknown status value → `ERR_INVALID_STATE`; same-status write and no-change PATCH are no-ops; artists list filters are `status` and `current_agreement_id` — `implementation/routes/artists.py:45-99`
- §3.2 — sunset window computed once at opening, never recomputed; close re-pins and excludes self from overlap scan — `implementation/services/core.py:86-95`, `implementation/routes/rate_schedules.py:117-129`
- §3.3 — trailing evaluation window = [clock−365d, clock] inclusive; availability inspects only HOLD/CONFIRMED engagements — `implementation/services/calculations.py:213-254`
- §3.3 — conversion copies `income_type`/`counterparty_name` from the opportunity; the engagement is created before the overlap check, so a failed conversion leaves it persisted as CONFIRMED with the opportunity still ACCEPTED — `implementation/routes/opportunities.py:210-228`
- §3.4 — exercise-born engagement carries `opportunity_id` = option's `source_opportunity_id` (or null) and empty `counterparty_name`; same orphan-on-overlap-failure behavior — `implementation/routes/options.py:109-126`
- §3.5 — agreement-resolution final tie-break by lowest `id` — `implementation/routes/income_events.py:50-57`
- §3.7 — per-request approver-role match evaluated after the PENDING state check; resubmission clears `rejection_note` and re-stamps `submitted_by_user_id` — `implementation/routes/approval_requests.py:50-57`, `implementation/routes/expenses.py:91-93`
- §3.8 — `rate_snapshot` entries carry `income_type`/`schedule_id`/`rate_bps` keys in line order; issue sweep guards (events still VERIFIED/SETTLED, expenses still APPROVED, recoup pin only if still null); amend skips upheld disputes already carried as adjustment lines — `implementation/services/calculations.py:344-348`, `implementation/routes/statements.py:154-170,196-207`
- §3.9 — escalation creates its audit unconditionally (365-day window and one-open-audit guards apply only to the direct-demand path); withdraw-revert treats only OPEN/UNDER_REVIEW disputes as active; audit window boundary is exactly 365 days before the clock instant, inclusive — `implementation/routes/disputes.py:118-146`, `implementation/routes/audits.py:41-49`, `implementation/services/core.py:160-164`

No sections added; all error codes, endpoint table, calculation formulas, and examples in the PRD were verified against impl and left untouched where already aligned.
