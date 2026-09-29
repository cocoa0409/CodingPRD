# Worklog — task_2140_403b_457_plan_admin

## Step 1: Create task directory — 2026-08-22T15:42:25.377Z

Created `tasks/task_2140_403b_457_plan_admin/` and `tasks/task_2140_403b_457_plan_admin/workspace/`.

## Step 3: Copy shared files — 2026-08-22T15:42:40.000Z

Copied `INSTRUCTION.md` → `tasks/task_2140_403b_457_plan_admin/workspace/INSTRUCTION.md`.

## Step 2: Generate scaffold — 2026-08-22T16:40:46.866Z

Generation complete. All three artifacts are written and the linter passes clean.

## Verdict block (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2140_403b_457_plan_admin/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2140_403b_457_plan_admin/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2140_403b_457_plan_admin/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    54
  §1.1 entities declared:     13
  §1.8 instances scanned:     26
  §1.9 instances scanned:     57
  Calls scanned (§1.8+§1.9):  977

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Files

- `SCAFFOLD.yaml` (§1.0–§1.7)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9)

## Counts

| Table | Count |
|---|---|
| Entities | 13 (Employer, Plan, Vendor, InformationSharingAgreement, Participant, UniversalAvailabilityNotice, EligibilityDetermination, ContributionElection, VendorAccount, RemittanceBatch, RemittanceCorrection, ParticipantRequest, TransferExchangeRequest) |
| State machines | 6 (Plan, ISA, ContributionElection, RemittanceBatch, ParticipantRequest, TransferExchangeRequest) |
| Concurrency rules (OCC) | 2 |
| Calculations | 14 |
| Validations | 43 (single ordered priority ladder) |
| Endpoints | 54 (incl. 2 computed reads + 1 `/_clock` test-driving endpoint) |
| Error codes | 53 |
| Roles | 5 (SystemOperator, PlanSponsorAdmin, ComplianceOfficer, VendorRepresentative, Participant) |
| §1.8 difficulty instances | 26 across 9 rules (3/3/3/2/3/3/3/3/3) |
| §1.9 corner instances | 74 across 9 sections — 57 full recipes + 17 `excluded_because` stubs |

## Difficulty calibration ("harder than expert")

Deliberately pushed above the Expert band on surface (13 entities / 54 endpoints / 53 errors / 14 calculations) *and* on density:

- **Archetype**: compliance/audit x quota-allocation; topology `graph` (Participant x Plan x Vendor mesh joined by VendorAccount + ISA, with a self-referential `ContributionElection.supersedes_election_id`); shape `cyclic`; role model `segregation_of_duties` — all four are the diversity-prioritized options in §0.3.
- **Rule 1** dual-variant across 3 domains: gross-vs-verified 402(g) room (enforcement is pinned to the *gross* basis), hardship gross-up vs 457(b) unforeseeable-emergency net-of-relief, contract-exchange vs plan-to-plan admissibility.
- **Rule 2** all three modes present: (a) three-way nested `min` for the 15-year service catch-up gated on qualified-organization status, (b) round-per-line-then-sum lost earnings (6576 vs 6575 cents), (c) pinned pre-attribution snapshot in the catch-up waterfall (splitting 150000/300000/550000 instead of failing with a 50000-cent remainder).
- **Rule 4** two 4-hop cascades from different triggers: late deposit -> correction -> account/plan counters -> posture blocking transfers; loan disbursement -> contract balances -> participant aggregates -> `loan_eligibility_flag` SUSPENDED.
- **Rule 8** three genuinely different interval geometries on three resources: half-open pay periods (adjacency allowed), closed election windows (adjacency collides), buffered ISA intervals (one clear day required).
- **Rule 9** three distinct conserved quantities: accumulated benefit, YTD deferral consumption, open-correction count <-> posture.

Domain traps encoded: 403(b) and 457(b) are **separate** 402(g) buckets; 457(b) takes the **greater of** final-3-year and age-50 (never both, and top-hat plans get no age-50 at all); 415(c) aggregates 403(b) across *all* employers but doesn't apply to 457(b); college tuition and home purchase are *not* unforeseeable emergencies; intranet posting alone is never a valid universal-availability notice; plan-to-plan transfers need no ISA while contract exchanges do.

All numeric assertions were computed in Python against the pinned formulas (business-day deadlines against a fixed 2026 federal-holiday list, per-line half-up rounding, floor-based vesting and 50%-of-vested caps). Logical clock default is fixed at `2026-08-01T00:00:00Z` per the skill's mandate.

## Step 4: Generate PRD — 2026-08-22T16:52:00.000Z

PRD generated at `workspace/PRD.md`.

## Output

**463 lines.** Built incrementally across 7 appends (never a one-shot Write), so no output-cap truncation.

## Section list

- §1 Introduction (3 paragraphs)
- §2 Global Specifications — 2.1 Actors, Identity Headers, and RBAC · 2.2 API Response Structure (verbatim) · 2.3 Pagination · 2.4 Resource Identity, Timestamps, and the Version Counter · 2.5 Optimistic Concurrency on Participant and Contract Writes · 2.6 The Rejection Ladder · 2.7 Money, Rounding, and the Logical Clock · 2.8 Statutory Regime Classification · 2.9 The Information Sharing Perimeter and Data Staleness · 2.10 Cascade Discipline: Contract, Participant, Plan · 2.11 Nested Paths and Left-to-Right Resolution
- §3 Business Logic (9 subsections) — 3.1 Sponsors, Providers, and the Plan Lifecycle · 3.2 The Vendor Perimeter · 3.3 Employees, UA Notices, and Eligibility · 3.4 Provider Contracts and Balance Reporting · 3.5 Contribution Capacity Across Vendors · 3.6 Electing, Approving, and Unwinding Deferrals · 3.7 Payroll Remittance, Timeliness, and Correction · 3.8 Loans, Hardships, and Unforeseeable Emergencies · 3.9 Contract Exchanges and Plan-to-Plan Transfers
- §4 Endpoint Definitions (4-column table, 54 rows)
- §5 Error Code Catalogue (2-column table, 53 rows)

## Coverage audit (scaffold-declared vs. present)

| Item | Declared | Covered |
|---|---|---|
| entities | 13 | 13 (all 141 field names in backticks) |
| state machines | 6 | 6 |
| state transitions | 36 | 36 (from/to pairs, preconditions, side effects) |
| calculations | 14 | 14 |
| validations | 43 | 43 (full priority ladder stated in order in §2.6) |
| concurrency rules | 2 | 2 |
| endpoints | 54 | 54 (exact method+path rows in §4) |
| error codes | 53 | 53 (each appears in §2/§3 narrative *and* §5 table) |
| roles | 5 | 5 (each `identity:` translated to prose) |
| state enum values | all | 0 missing |
| entity enum values | all | 0 missing |

## Hard contract reports

```
Field coverage check:
- entities[].fields: 141 required, 141 present, 0 missing
- endpoints[].request_body/input/output: 129 required, 129 present, 0 missing
- endpoints[].query_params: 2 required, 2 present, 0 missing
Status: PASS
```
```
Rule coverage check:
- validations[] with priority: 43 checked, 43 expressed in prose (§2.6 ordered ladder), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_<parent>_version + ERR_STALE_VERSION/412 all named), 0 missing
- state_machines[].transitions: 36 checked, 36 fully expressed, 0 missing
- calculations[]: 14 checked, 14 fully expressed (no pseudocode, no fuzzy words), 0 missing
- validations[] conditions: 43 checked, 43 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 54 checked, 54 expressed, 0 missing
- entities[].fields[] structured content: 141 checked, 141 reconstructible from prose, 0 missing
- sibling-branch symmetry: 6 groups checked (403b/457b catch-up, gross/verified basis, hardship/UE ceiling, exchange/transfer admissibility, DISBURSED/PAID fulfilment fork, deposit/compliance axes), 6 with equal prose density, 0 asymmetric
Status: PASS
```
```
Path purity check (§3 only):
- backtick tokens scanned: 914
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Notes: §2.2 verified byte-identical to `section-2.2-response-structure.md`. Fuzzy-word scan clean. `UniversalAvailabilityNotice` (the one `common_fields: false` entity) is explicitly stated to carry only `id` and `created_at`. Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced.

Orchestrator verification: 5 top-level sections present, 54 endpoint table rows, 53 error table rows — no truncation.

## Step 6: Generate implementation — 2026-08-22T17:14:00.000Z

Implementation complete at `workspace/implementation/`.

## Module list (3,263 lines total)

| File | Lines | Contents |
|---|---|---|
| `start.sh` | 8 | Guarded `pip install` (skipped when flask importable), `exec python3 app.py` |
| `requirements.txt` | 1 | `flask==3.0.3` |
| `app.py` | 49 | Blueprint registration, `ApiError`/HTTP/unhandled error handlers, `0.0.0.0:$PORT` (default 10000) |
| `store.py` | 142 | 13 in-memory dicts, logical clock (boots at `2026-08-01T00:00:00Z`), UUID/timestamp/version helpers, query helpers |
| `errors.py` | 68 | All 53 error IDs -> HTTP status |
| `envelope.py` | 47 | `meta`/`response_type`/`data` envelope, `limit`/`offset`/`total_count`/`has_more` |
| `validate.py` | 197 | Rung-3 field parsers (int rejects bools), pagination 10/1-100/0 |
| `auth.py` | 135 | Rungs 1/2 decorator, 12 typed existence lookups, ownership predicates |
| `calc.py` | 514 | All constants + 14 calculations (regime, notice validity, eligibility ladder, both catch-up capacities, 402(g) gross/verified, 415(c), pinned attribution waterfall, loan max, distribution ceiling, business-day deadlines, per-line-rounded lost earnings, excise tax) |
| `derive.py` | 84 | Contract->participant->plan cascade recomputation |
| `serialize.py` | 63 | Public views; clock-dependent `data_stale` / `attained_age_at_year_end` derived at read |
| `routes/core.py` | 228 | Employers, vendors, plans, clock |
| `routes/isa.py` | 133 | Agreements, status machine, data feeds |
| `routes/participants.py` | 313 | Participants, UA notices, eligibility determinations, both computed reads |
| `routes/accounts.py` | 137 | Vendor accounts + OCC-guarded balance report |
| `routes/elections.py` | 259 | Elections, decision waterfall, revoke |
| `routes/remittance.py` | 301 | Batches, deposit/reverse, correction cascade, settle |
| `routes/requests.py` | 312 | Loan/hardship/UE pipeline |
| `routes/movements.py` | 272 | Exchanges & plan-to-plan transfers |

## Endpoint registration
**54 registered vs 54 declared** — exact match, path-for-path.

## Boot check
`PORT=18745 bash start.sh` -> HTTP 200 on `GET /plan-admin/plans` within ~2s; all 9 list collections return `total_count=0` on a fresh process (no seeding anywhere); clock reads `2026-08-01T00:00:00.000Z`.

## Verified behaviour (4 end-to-end smoke suites)
Arithmetic hand-checked: small-plan 7-business-day deadline skipping the 19 Jun holiday; large-plan 15th-business-day-of-next-month; per-line half-up lost earnings (378 + 756 = 1134, excise 170) vs. sum-then-round; the pinned attribution waterfall (basic 2,450,000 -> service 300,000 -> age-50 50,000); 457(b) final-3-year as `min(2xbasic, basic+underutilized) - basic`; loan `cap_statutory`/`cap_vested` before and after disbursement; exact-compensation movement reversal. Ladder ordering confirmed for ~25 error codes including `ERR_PLAN_FROZEN`, `ERR_SEGREGATION_OF_DUTIES`, `ERR_STALE_VERSION`, `ERR_ISA_DATA_STALE` (after `ERR_ISA_NOT_ACTIVE`), `ERR_PLAN_UNDER_CORRECTION`, and the exchange/transfer over-amount asymmetry.

## Two judgement calls worth flagging
1. **§2.6 ladder over §3.x prose ordering** where they disagree: notice check (rung 16) runs before eligibility (rung 19) on election approval, and exchange-vendor approval (rung 26) before plan-permission shape (rung 27) — §3.6/§3.9 list them the other way, but §2.6 explicitly claims precedence for multi-violation requests.
2. **Two conditions have no error code in the catalog**: plan termination with open corrections -> `ERR_PLAN_UNDER_CORRECTION` (409), and batch reversal blocked by a settled correction -> `ERR_INVALID_STATE_TRANSITION` (409). Both share 409 with the plausible alternatives.

## Step 5: Generate unit tests — 2026-08-22T17:26:00.000Z

Test infrastructure and suite are complete and verified.

## Files written

**`test_helpers/`** (9 files, all non-empty, imports clean)
| file | contents |
|---|---|
| `types.py` | 20 status/role enums + 13 entity TypedDicts. `UniversalAvailabilityNotice` is the only `common_fields: false` entity — its TypedDict carries `id`/`created_at` only. |
| `api_client.py` | `ApiClient(GenericApiClient)` with one method per PRD endpoint (all 54, `/plan-admin` prefix). |
| `api_errors.py` | 53-member `ApiErrorId` + HTTP map, registered via `set_error_http_status_map`. |
| `assertions.py` | per-entity assertions + domain invariants (`assert_vested_balance_consistent`, `assert_attribution_sums_to_elected_amount`, `assert_line_breakdown_sums_to_total`, `assert_plan_compliance_posture_follows_count`, `assert_limit_summary_reconciles`). |
| `factories.py`, `constants.py` | input-only payload factories; statutory thresholds + the fixed 2026 holiday calendar. |
| `test_users.py` | opaque-role constants **plus** `make_sponsor_headers` / `make_vendor_headers` / `make_participant_headers` builders for the three `entity_backed` roles (identity threading). |
| `fixtures.py` | ~730 lines: 40 primitives + Tier 1-5 composites (`setup_plan_env`, `setup_403b_with_agreement`, `setup_two_vendor_403b`, `setup_election_ready`, `setup_effective_election`, `setup_request_under_review`, `setup_late_deposit`, `setup_withheld_batch`, `setup_accepted_exchange`, `setup_approved_exchange`). |

**`test_suite/`** — `conftest.py` + 9 test files, **108 tests**, all collect cleanly (`pytest --collect-only`: 108 collected, 0 errors):

| file | tests |
|---|---|
| test_01_sponsors_plans_and_lifecycle | 14 |
| test_02_information_sharing_perimeter | 6 |
| test_03_eligibility_and_notices | 6 |
| test_04_contribution_capacity | 10 |
| test_05_election_lifecycle | 15 |
| test_06_remittance_and_corrections | 17 |
| test_07_loans_hardships_and_emergencies | 17 |
| test_08_movements_and_transfers | 13 |
| test_09_access_control_and_concurrency | 10 |

## Instances translated vs skipped

- **Difficulty (queue A): 26/26 translated, exactly 2 tests each = 52 tests.** Each pair splits the instance along its own contrast (winning-vs-losing rung, gross-vs-verified basis, blocked-vs-lifted gate, execute-vs-reverse).
- **Corner (queue B): 56/57 translated, 1 test each.**
 - **Skipped: `Corner/entities/vendor_account_system_fields_input_ignored`** — it asserts that supplying the system fields `ytd_elective_deferrals_cents` / `outstanding_loan_balance_cents` to contract creation returns `ERR_INVALID_REQUEST`. PRD rung 3 defines well-formedness as required fields present, enums in range, cents in bounds, dates parseable — it never says unknown/extra body fields are rejected. Two PRD-only implementers could faithfully ignore extras vs. reject them, so unique derivability fails. Gap left as a gap; no placeholder, no weakened assertion.
- **17 `excluded_because:` stubs: not translated**, and every `difficulty_instance` cross-reference was machine-verified to resolve to a real §1.8 instance name.

## Design-tag audit

Automated audit (`ast` walk over all 108 tests): **every test carries exactly one `Design:` line**; 0 untagged, 0 dual-tagged, 0 unknown tags, 0 tags pointing at stubs. Every difficulty instance >=2, every non-stub corner instance >=1.

## PRD-citation audit

Automated verbatim check: every quoted citation, whitespace-normalised, survives a literal match against `workspace/PRD.md` — **0 non-verbatim quotes across 108 tests**. No `skip`/`skipif`/`xfail` anywhere; no mention of "scaffold" or scaffold section references in emitted code.

## One deliberate deviation from a pre-computed literal

`Corner/entities/plans_listing_returns_pagination_envelope` asserts `has_more == true` at `limit=2, offset=1` over 3 rows. PRD §2.3 defines `has_more` as "whether any matching row falls beyond the current window" — at offset 1 the window covers rows 2 and 3, so nothing lies beyond and a correct implementation returns `false`. The yaml's literal is arithmetically wrong against the contract. The test asserts both windows instead: `offset=0 -> has_more true`, `offset=1 -> has_more false`, which exercises the same claim and is uniquely derivable from PRD. I also dropped that instance's `plan_type`-filter assertion (the filter parameter names for `/plans` appear only as prose "filtered by sponsor, plan type or status", not as named fields) and kept the listing unfiltered, which yields the same row counts.

## Step 7: Run tests and iterate — 2026-08-22T17:38:00.000Z

All 8 parallel rounds pass 108/108.

## Summary

**Iterations run:** 2 (sweep 1 -> single fix -> sweep 2 clean).

**Sweep 1 result:** 107/108 in all 8 rounds — one deterministic (non-flaky) failure, `test_vendor_account_vested_balance_is_floored` in `test_suite/test_01_sponsors_plans_and_lifecycle.py`, asserting `2222333 == 2222332`.

**Tests deleted:** none. The single failure passed STEP 1a (PRD.md:230 states the rule verbatim: "`vested_balance_cents` is always derived, never supplied: it is `accumulated_benefit_cents` multiplied by `vested_percentage_bps`, divided by 10000, with the result floored to a whole cent.") and STEP 1b (a floor of an exact product is uniquely derivable — no two faithful readings diverge).

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none. The implementation was correct.

**Fix applied to `test_suite/`** (STEP 2 — test assertion mis-translated the PRD formula):
- `test_suite/test_01_sponsors_plans_and_lifecycle.py`, `test_vendor_account_vested_balance_is_floored` — the test's pre-computed literal was arithmetically wrong. `3_333_333 x 6667 = 22_223_331_111`; `/ 10000 = 2_222_333.1111`; floored = **2_222_333**, not `2_222_332`. Corrected both the contract-level `vested_balance_cents` literal and the participant-aggregate `total_vested_balance_cents` literal, which is the same figure summed over one open contract. This makes the test *more* faithful to PRD §3.4 (it now actually tests the floor rather than an off-by-one), and no assertion was weakened — the exact-value check is preserved.

**Verification:** the corrected expectation is a true floor boundary — the exact quotient is `2_222_333.1111`, so a truncating implementation and a rounding-half-up implementation would differ here, meaning the test still discriminates the PRD-required floor semantics from round-half-up.

Orchestrator verification: results.1..8.json all report 108/108.

## Step 8: Finalize PRD — 2026-08-22T17:46:00.000Z

## Result: zero edits — PRD_FINALIZED.md is byte-identical to PRD.md

`workspace/PRD_FINALIZED.md` created as an exact copy. This is the legitimate "pure test-arithmetic bug" outcome the method anticipates.

### Line counts
- PRD.md: 463 lines
- PRD_FINALIZED.md: 463 lines
- Delta: 0 lines, 0.00% (md5 identical: `65fb990c...`)

### Changes
None.

### Why no edit was warranted

The sole `<step_7_diff>` item was a `test_suite/` literal correction with no `implementation/` change, no `test_helpers/` change, and no assertion weakening. Verified independently that the implementation exhibits exactly the behavior PRD.md already states, so there is no silence and no mismatch to pin.

Subject verified: derivation and aggregation of `vested_balance_cents`.

Impl paths enumerated and read:
- `implementation/calc.py:513-514` — `vested_balance()` is `accumulated_benefit_cents * vested_percentage_bps // 10000`. Python integer floor division on non-negative inputs = exact-product-then-floor, which is verbatim PRD.md:230. For the failing fixture: `3_333_333 x 6667 = 22_223_331_111`, `// 10000 = 2_222_333` — the implementation was right and the test literal (`2_222_332`) was wrong.
- `implementation/derive.py:6-8` — `recompute_vendor_account()`, the single recompute path, calls the same `calc.vested_balance`.
- All recompute callsites: `routes/accounts.py:54` (contract open, PRD §3.4), `routes/accounts.py:127` (balance report, PRD:234), `routes/requests.py:304` (HARDSHIP/UNFORESEEABLE_EMERGENCY payment, PRD:326), `routes/movements.py:234-235` (movement execution, PRD:340), `routes/movements.py:262-263` (movement reversal, PRD:342). Every one routes through the identical formula.
- `implementation/derive.py:22-23` — `total_vested_balance_cents` sums the already-floored per-contract `vested_balance_cents` over `status == "OPEN"` contracts only, exactly PRD.md:172. The implementation does not re-floor an aggregate product.

Wording adjustment: n/a — no sentence was changed.

## Step 9: Complete PRD — 2026-08-22T17:55:00.000Z

`PRD_COMPLETED.md` is written. Structure verified intact: 5 top-level sections, 54 endpoint rows, 53 unique error-code rows.

## Result

- **Source vs output:** `PRD_FINALIZED.md` 463 lines / 101,784 chars -> `PRD_COMPLETED.md` 463 lines / 107,669 chars (**+5,885 chars**, 0 line delta — every edit is an in-paragraph insert or revision; no new paragraphs, no new sections).
- **47 changes across 44 lines: 39 ambiguity-pins, 8 mismatch-revisions.**

### Changes

**Mismatch-revisions (PRD said something impl does not do)**
- `§2.6 rung 12` — revise — mismatch — rung reserved for movements; also fires on plan termination with open corrections — `routes/core.py:166-169`
- `§2.10` — revise — mismatch — "each row the cascade touches" bumped; plan counters are recomputed in place, plan `version` moves only on explicit plan transitions — `derive.py:40-69`
- `§3.3` — revise — mismatch — registration "initialises every cross-contract aggregate to zero"; `lifetime_elective_deferrals_cents` starts at `prior_employer_elective_deferrals_cents`, and `attained_age_at_year_end` is derived per read, not stored — `routes/participants.py:191`, `serialize.py:30`
- `§3.5` — revise — mismatch — `plan_year` described as narrowing the view; it is echoed back and narrows nothing, and `plan_id` is a required query param — `routes/participants.py:390-402`
- `§3.6` — revise — mismatch — approval check order listed eligibility before notice; impl is SoD (rung 7) -> state -> plan status -> notice (16) -> eligibility (19) — `routes/elections.py:307-337`
- `§3.6` — revise — mismatch — top-hat test described last but sits at rung 18, ahead of window/catch-up rungs 31/35/36 — `routes/elections.py:218-243`
- `§3.8` — revise — mismatch — flag suspension keyed on "plan-type bucket"; impl keys on the `(employer_id, plan_type)` pair — `calc.py:414-425`
- `§3.9` — revise — mismatch — prose ordered plan-document test before vendor-approval test; rung 26 runs first — `routes/movements.py:40-50`

**Ambiguity-pins (PRD silent)**
- `§2.2` — insert — `api_request_timestamp` reads the logical clock; `api_request_id` is `req_` + 20 upper-case alphanumerics — `envelope.py:12-17`
- `§2.3` — insert — `created_at` ties broken by write order — `store.py:108`
- `§2.6 rung 9` — insert — also covers data feed on `TERMINATED` agreement and batch reversal over a `SETTLED` correction — `routes/isa.py:124`, `routes/remittance.py:204-207`
- `§2.9` — insert — with multiple agreements per plan-vendor pair, the earliest-created qualifying `ACTIVE` one is consulted — `calc.py:128-138`
- `§3.1` — insert x2 — duplicate `ein` / `vendor_code` -> `ERR_INVALID_REQUEST` — `routes/core.py:36,68`
- `§3.1` — insert — termination with open corrections -> `ERR_PLAN_UNDER_CORRECTION` — `routes/core.py:168`
- `§3.1` — insert — termination cascade rewrites participant aggregates without a participant `version` bump — `routes/core.py:205`
- `§3.2` — insert — inverted agreement window -> `ERR_INVALID_REQUEST` — `routes/isa.py:27`
- `§3.2` — insert — `PENDING->ACTIVE` on a non-active plan -> `ERR_PLAN_NOT_ACTIVE`; the only agreement hop that tests plan status — `routes/isa.py:107-111`
- `§3.2` — insert — feed against `TERMINATED` agreement -> `ERR_INVALID_STATE_TRANSITION` — `routes/isa.py:124-126`
- `§3.3` — insert — only a non-`NONE` `asserted_exclusion` is tested; `NONE` is never contradicted — `routes/participants.py:329`
- `§3.3` — insert — `exclusion_basis` also null for `INELIGIBLE_PLAN_NOT_ACTIVE` — `routes/participants.py:348`
- `§3.4` — insert — contract opening refreshes participant aggregates without a `version` bump — `routes/accounts.py:65`
- `§3.5` — insert — `annual_additions_cents` / `annual_additions_limit_cents` reported null on a 457(b) bucket — `calc.py:310`
- `§3.6` — insert — inverted election window -> `ERR_INVALID_REQUEST` — `routes/elections.py:195`
- `§3.6` — insert — rejection carries the same rung-7 SoD and plan-status guards as approval — `routes/elections.py:307-322`
- `§3.7` — insert — `pay_period_end` on or before start -> `ERR_INVALID_REQUEST` — `routes/remittance.py:44`
- `§3.7` — insert — `deposit_date` before `withholding_date` -> `ERR_INVALID_REQUEST`, tested after rung 29; skipped on redeposit from `REVERSED` — `routes/remittance.py:129-133`
- `§3.7` — insert — reversal `reason` is required; settled-correction block -> `ERR_INVALID_STATE_TRANSITION` — `routes/remittance.py:197,206`
- `§3.7` — insert — `deadline_date` survives reversal — `routes/remittance.py:231-235`
- `§3.8` — insert — `plan_id` required on the loan-capacity view — `routes/participants.py:428`
- `§3.8` — insert — `cap_statutory_cents` / `cap_vested_cents` reported unfloored, may be negative — `calc.py:388-392`
- `§3.8` — insert — UE relief and distribution-ceiling tests run only at approval, unlike the loan tests — `routes/requests.py:204-227`
- `§3.8` — insert — `loan_term_months` must be a positive integer; recorded but read by no calculation — `routes/requests.py:53`
- `§3.9` — insert — both plans must be `ACTIVE`/`FROZEN` at filing; sponsor-admin ownership matches participant's employer or either plan's employer, retested at execution — `routes/movements.py:17-29,93-95`
- `§3.9` — insert — the exchange agreement is sought between the *source* plan and the destination vendor, with no data class demanded — `routes/movements.py:41`
- `§3.9` — insert — execution over-amount answers `ERR_ACCUMULATED_BENEFIT_REDUCED` / `ERR_TRANSFER_AMOUNT_EXCEEDS_BENEFIT` by kind — `routes/movements.py:223-228`
- `§4` — revise x11 — list-filter query parameter names spelled out on every list row (`employer_id`, `plan_type`, `deposit_state`, `supersedes_election_id`, `superseded`, etc.), which the prose named only descriptively — `routes/*.py` list handlers

Orchestrator verification: PRD_COMPLETED.md has 5 sections, 54 endpoint rows, 53 error rows.
