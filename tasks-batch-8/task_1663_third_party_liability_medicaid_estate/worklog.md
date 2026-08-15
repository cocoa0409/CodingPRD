# Worklog — task_1663_third_party_liability_medicaid_estate

## Step 1: Create Task Directory — 2026-08-14T05:54:00.000Z

Task directory `tasks/task_1663_third_party_liability_medicaid_estate/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher. Step 1 treated as DONE per invocation args; no index scan performed, no other task directory touched.

## Step 2: Generate Scaffold — 2026-08-14T06:39:00.000Z

All three scaffold artifacts are generated and pass clean lint. Summary of what was built for `task_1663_third_party_liability_medicaid_estate`:

**Files**
- `/home/ubuntu/github/CodingPRD/tasks/task_1663_third_party_liability_medicaid_estate/SCAFFOLD.yaml` (§1.0–§1.7 only)
- `/home/ubuntu/github/CodingPRD/tasks/task_1663_third_party_liability_medicaid_estate/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single top-level key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1663_third_party_liability_medicaid_estate/SCAFFOLD_CORNER_DESIGN.yaml` (single top-level key `scaffold_corner_design`)

**SCAFFOLD.yaml contents**
- Complexity profile: compliance_audit primary + multi_party_negotiation secondary; layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, derived_field_reconciliation; flat topology; segregation_of_duties role model; immediate consistency
- **Entities: 9** — Member, TplCase (parallel dims: resolution status × litigation status), ExpenseClaim, Lien, Settlement, RecoveryPosting, EstateCase, HardshipWaiver, CommunicationNotice
- **State machines: 9** entries, incl. cyclic Settlement negotiation (OFFERED⇄COUNTERED), parallel TplCase dimensions, waiver appeal loop (DENIED→PENDING), notice retry loop, lazy SOL/TIME_BARRED expiries, and compensation reverts (SATISFIED→FILED, RESOLVED→SETTLEMENT_PENDING, WAIVED→CLAIM_FILED, DISBURSED→ACCEPTED)
- **Calculations: 5** — lien_perfected_amount (cap aggregation), settlement_recovery_amount (subrogation vs reimbursement variants + pinned cost-share order), estate_claim_amount (provisional vs final variants), contractor_commission (3-tier, per-posting rounding pinned), hardship_reduction (nested min/max with waiver-type branch)
- **Validations: 10** priority levels (auth → role → request shape → existence → SoD → state → temporal → constraint → fiscal)
- **Endpoints: 43** (incl. computed read `GET /recovery/cases/{caseId}/accounting-summary` and test-driving `POST /recovery/_clock/set_current_utc` with mandated default 2026-08-01T00:00:00Z)
- **Error catalog: 24** errors — all referenced by at least one design instance
- **RBAC: 5 roles** (SystemAdmin, RecoverySpecialist, RecoverySupervisor, RecoveryAccountant, EstateRecoveryOfficer; all opaque, SoD enforced via `created_by_user_id`)
- **Concurrency rules: 2** OCC entries (lien amend on `Lien.version`, settlement create on `TplCase.version`, both ERR_STALE_VERSION/412)

**SCAFFOLD_DIFFICULTY_DESIGN.yaml: 19 instances** — all 9 §0.5 rules with ≥2 instances each (combinatorial_formula has 3, one per mode a/b/c). All formula-derived asserts are pre-computed literals (e.g., reimbursement 200000 vs subrogation 150000 on identical inputs; commission rounding 10002/10005 summing to 20007 ≠ aggregate-rounded 20006).

**SCAFFOLD_CORNER_DESIGN.yaml: 51 instances** (50 active + 1 `excluded_because` stub) across all nine guide sections: entities, state_machines, calculations, validations, endpoints, errors, rbac, cross_cutting_complexity_layers, consistency_model.

**Verification**: `scaffold_lint.py` verdict — `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5` (43 endpoints, 506 calls scanned). Additional scripted checks passed: instance-name uniqueness across both files, all `grounds:` refs resolve, no forbidden concurrency vocabulary, every error code exercised. Two authoring fixes along the way: quoted `[`/`]`-bearing JSONPaths and grounds tokens for YAML flow collections, and renamed the expense-claims sub-resource path param to `{id}` to satisfy the linter's FK reverse-reachability prefix matching.

## Step 3: Copy Shared Files — 2026-08-14T06:41:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1663_third_party_liability_medicaid_estate/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-14T07:05:00.000Z

PRD generated and verified. Output: `/home/ubuntu/github/CodingPRD/tasks/task_1663_third_party_liability_medicaid_estate/workspace/PRD.md` (305 lines).

## PRD Section List

- **§1 Introduction** (2 paragraphs — business context + role/clock framing)
- **§2 Global Specifications** — 2.1 RBAC (5 roles, opaque-identity prose for each), 2.2 API Response Structure (verbatim block, byte-identical incl. `req_RANDOMALPHANUM123456` / `2025-05-24T10:30:00.123Z` / `"data": { }`), 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ascending), 2.4 Common Resource Properties, 2.5 Logical Clock & Statutory Calendar (default `2026-08-01T00:00:00Z`, lazy SOL cascade), 2.6 Monetary Precision (integer cents, round half-up, commission rounding-order pin), 2.7 OCC (`expected_lien_version` / `expected_case_version` → `ERR_STALE_VERSION` 412), 2.8 Validation Sequencing (priorities 1–9 + OCC-last, explicit prose), 2.9 Cascading Reconciliation, 2.10 Nested Resource Retrieval (left-to-right), 2.11 Member Communication Obligations
- **§3 Business Logic** — 3.1 Enrolling Members / Recovery Approach, 3.2 Case Identification + Litigation Track, 3.3 Statutory Lien (perfect/amend/release, freeze, cap), 3.4 Settlement Negotiation + dual-variant recovery formula, 3.5 Postings / tiered commission / reversal compensation / accounting summary, 3.6 Estate Recovery (mark-deceased → file-claim → record-payment), 3.7 Hardship Waivers (approve/deny/appeal/rescind), 3.8 Notices & Delivery Deadlines
- **§4 Endpoint Definitions** — 43 rows, 4 columns only; **§5 Error Code Catalogue** — 24 rows, 2 columns only

## Coverage-Audit Results (mechanical, 2 passes)

```
Contract 1 (Field-Name Coverage):
- entities[].fields: 61 required, 61 present, 0 missing
- endpoints[].request_body: 31 required, 31 present, 0 missing
- endpoints[].query_params: 8 required, 8 present, 0 missing
- endpoints[].path_params: 9 required, 9 present, 0 missing
- common/envelope: 17/17; computed-read outputs (accounting summary + clock): 5/5
- enum/state values: 50/50; roles: 5/5; error IDs: 24/24
Status: PASS

Contract 2 (Rule Coverage — manual walk, all scaffold rule tables):
- validations[] priority: 9 tiers + OCC-last expressed as ordered prose in §2.8 — 0 missing
- concurrency_rules[]: 2/2 expressed (write_endpoint + occ field + ERR_STALE_VERSION/412 in §2.7; stale-version framing only)
- state_machines[].transitions: 41/41 expressed (incl. alias row rendered as "RESOLVED reachable only through lien satisfaction; no direct resolve action")
- calculations[]: 5/5 expressed as reconstructible prose (lien perfected amount, both settlement_recovery variants with pinned evaluation order, estate provisional/final with zero floor, 3-tier commission with per-posting rounding pin, hardship FULL/PARTIAL with nested max/min in words)
- validations[] conditions: all 24 error IDs matchable to trigger prose in §2/§3
- endpoints[].side_effects / applies_to scopes: all expressed (SoD→2 endpoints, SOL→4 operations, fiscal→4 operations, uniqueness→6 operations)
- field structured content: defaults/nulls now explicit (attorney_notified_at, decided_reduction_cents, commission/net while PENDING, claim_amount until filed, etc.)
- sibling-branch symmetry: counter/reject/accept/satisfy/release pairs and FULL/PARTIAL + SUBROGATION/REIMBURSEMENT variants at equal density
Status: PASS

Contract 3 (§3 Path Purity): 486 backtick tokens scanned; 0 path tokens, 0 bare HTTP methods, 0 method+path combos. Status: PASS
```

## Zero-Silence Rule Adjudications

1. **Posting-create on non-ACCEPTED settlement** — scaffold's endpoint description requires ACCEPTED but validation priority 6 doesn't enumerate the error; rendered as rejection with `ERR_INVALID_STATE_TRANSITION` (the only state-error fit), flagged here as the one inferred mapping.
2. **Lazy SOL expiry trigger scope** — scaffold trigger says "any write on the case or its lien/settlement children" while validation applies_to names four operations; rendered both faithfully: the cascade fires on any write past `sol_date`, and exactly the four named operations (negotiation open, accept, amend, post) reject with `ERR_SOL_EXPIRED`.
3. **Alias transition row** (`SETTLEMENT_PENDING → RESOLVED` "not used...no direct endpoint") — rendered as an explicit negative statement rather than a second transition.
4. **Lien filing from states other than IDENTIFIED/ATTORNEY_NOTIFIED** — `ERR_ATTORNEY_NOT_NOTIFIED` reserved for IDENTIFIED per the error catalog; other wrong states mapped to generic `ERR_INVALID_STATE_TRANSITION`.
5. **Unit conversions** — constants rendered in dollars with exact cent values preserved (250,000 cents/$2,500 cap; 5,000,000/$50,000 homestead; 3,000,000/$30,000 income; 100,000/$1,000 commission tiers); day/year constants spelled out (ninety days, fourteen days, three hundred sixty-five days, thirty days, three years).
6. **`posting_count` semantics** — scaffold output shape lists it without definition; rendered as "the number of POSTED postings contributing to the totals," consistent with the calculation's PENDING/REVERSED exclusion note.
7. **Version bumps on cascade mutations** — general rule ("every mutation refreshes `updated_at`/increments `version`") stated in §2.4, with scaffold-explicit bumps (case version on expense-claim add, notify-attorney, litigation, close, settlement open; lien version on amend) called out in §3 narratives.

One audit-tooling note: the first Contract-1 pass falsely reported ~150 missing names because the token regex was confused by §2.2's triple-backtick JSON fences (parity inversion); stripping fenced blocks before scanning confirmed full coverage — the PRD text itself was correct.

## Step 5: Generate Unit Tests — 2026-08-14T07:45:00.000Z

Generation complete and fully audited. Final tree and summary:

## Generated files

**test_helpers/** (9 files): `types.py` (14 enums + 9 entity TypedDicts), `api_client.py` (33 endpoint methods, `/recovery` prefix), `api_errors.py` (24 error IDs + HTTP map registered with the framework), `assertions.py` (9 entity assertions + lien-outstanding and settlement-split invariants), `factories.py` (input-field-only payload factories), `constants.py` (PRD thresholds: 250000 cap, 0.35 ratio, 0.25 cost share, commission tiers, homestead/income caps, 365/30/14/90-day windows), `test_users.py` (5 opaque roles + per-instance builders + NO_AUTH_HEADERS), `fixtures.py` (tiered composites: `setup_case_with_lien`, `setup_settlement_offered`, `setup_accepted_settlement`, `setup_pending_posting`, `setup_posted_recovery`, `setup_estate_opened/claim_filed/pending_waiver`, `find_notice`), `__init__.py` barrel.

**test_suite/** — 89 tests in 9 files: `test_01` members/case identification (7), `test_02` case workflow & litigation (7), `test_03` liens (15), `test_04` settlements (15), `test_05` SOL temporal rules (6), `test_06` postings & commission (15), `test_07` estate recovery (10), `test_08` hardship waivers (9), `test_09` auth/validation-order/notices (5).

## Test counts per queue
- **Queue A (Difficulty): 39 tests** — all 19 instances covered with ≥2 tests (one instance got 3).
- **Queue B (Corner): 50 tests covering 49 instances.**

## Instances skipped (with reason)
1. **Corner/errors/error_catalog_triggerability** — meta-audit instance with an empty `trigger:`; its assertion is about the design indices themselves, not API behavior, and no verbatim PRD rule exists to assert. Translating it would be freelance test invention.
2. **Corner/calculations/variant_selection_by_state_code** — `excluded_because:` stub, not translated per rule; cross-reference verified resolving to `Difficulty/dual_variant_calc/settlement_recovery_subrogation_vs_reimbursement` (3 tests).

## Relaxations applied (two-reader adjudication, no skips)
- **member_create_system_field_input_ignored** / **version_increments_on_each_mutation**: PRD §2.4 never pins the initial version value, so absolute `version == 1` assertions were dropped; kept server-minted `id`/`created_at` assertions and exact +1-per-mutation deltas (explicitly PRD-stated).
- **lien_amend_state_beats_sol_temporal**: kept the error-id assertion (state check precedes temporal per §2.8's fixed order); dropped the "no lazy-expiry side effect" sub-assertion — §2.5's "next write action ... moves the case to SOL_EXPIRED" does not uniquely determine whether the cascade fires when an earlier check rejects.
- **Date adaptations forced by the fixed default clock (2026-08-01)**: `settlement_create_temporal_beats_constraint` uses injury 2023-08-01 (sol == default clock) then advances one day — the recipe's 2023-01-01 sol is unreachable without a backward clock move, which PRD does not sanction; `lien_amend_state_beats_sol_temporal` omits the backward move since the default clock is already past the 2026-01-01 sol.

## Stage-2 self-audit results
- All 89 tests collect under pytest; helpers package imports cleanly.
- Every difficulty instance has ≥2 `Design: Difficulty/...` tags; every translated corner instance ≥1 `Design: Corner/...` tag; all tags resolve to real instance names; no stub tagged.
- Every test docstring ends with exactly one Design line as its last line (C4).
- Every PRD citation's distinctive ≥8-word substring survives normalized grep of `workspace/PRD.md` (C1/C2/C3).
- No `pytest.mark.skip`/`skipif`/`xfail`; no scaffold references in generated code.

## Step 6: Generate Implementation — 2026-08-14T07:45:00.000Z

Implementation complete and verified. All files compile, the server boots via `bash start.sh` on `$PORT`, and two consecutive boots confirmed empty in-memory state each time. A 130-assertion smoke suite replicating the scaffold's corner/difficulty design recipes passes end to end.

## Summary

### File list (all under `/home/ubuntu/github/CodingPRD/tasks/task_1663_third_party_liability_medicaid_estate/workspace/implementation/`)
- `start.sh` — guarded pip install (`import flask` probe), `exec python3 app.py`, foreground, `$PORT` (default 10000), `0.0.0.0`
- `requirements.txt` — flask>=3.0,<4
- `app.py` — Flask app factory, blueprint registration, envelope-shaped error handlers (ApiError, 404, 405, catch-all)
- `db.py` — in-memory dict stores (9 entity tables), insertion sequence, `LogicalClock` pinned at `2026-08-01T00:00:00Z`, `new_entity`/`touch`/`pub` helpers (id/created_at/updated_at/version, 3-fractional-digit ISO timestamps from the logical clock)
- `errors.py` — all 24 catalog error IDs + `ApiError`
- `response.py` — exact envelope: `meta.{api_request_id, api_request_timestamp}`, `response_type` object/array/error, `data`; pagination fields `limit`/`offset`/`total_count`/`has_more` in meta for lists only
- `middleware.py` — `X-User-ID`/`X-User-Role` validation (priority 1) + role gate (priority 2)
- `util.py` — body-shape validators (priority 3), calendar math, `Decimal` ROUND_HALF_UP helpers, pagination (default 10, min 1, max 100)
- `services.py` — calculations, constants, finders, notice factory, derived-field recompute, SOL lazy-expiry cascade, negotiation-freeze check
- `routes/`: `members.py`, `cases.py`, `liens.py`, `settlements.py`, `postings.py`, `estates.py`, `waivers.py`, `notices.py`, `clock.py`

### Endpoints: 42 (full §1.5/§4 table, all under `/recovery`)

### State machines implemented (8)
Member (ACTIVE→DECEASED), TplCase resolution track (7 statuses, lazy SOL expiry, cyclic LIEN_FILED↔SETTLEMENT_PENDING), TplCase litigation track (parallel dimension, NO_SUIT/SUIT_FILED/JUDGMENT/SUIT_DISMISSED with refile), Lien (FILED/AMENDED/SATISFIED/RELEASED/EXPIRED with satisfaction↔reversal compensation), Settlement (OFFERED↔COUNTERED cycle, ACCEPTED/DISBURSED compensation), RecoveryPosting (PENDING/POSTED/REVERSED), EstateCase (OPENED/CLAIM_FILED/PAID/WAIVED/TIME_BARRED with auto-PAID at zero outstanding), HardshipWaiver (PENDING/APPROVED/DENIED/RESCINDED with single DENIED→PENDING appeal), CommunicationNotice (QUEUED/FAILED→DELIVERED retry loop with lateness recompute).

### Calculations implemented (5)
`lien_perfected_amount` (injury-date-filtered basis, min with 250000 cap), `settlement_recovery_amount` (both variants: REIMBURSEMENT min-chain floored at 0; SUBROGATION pinned pre-cost order with 25% cost-share cap), `estate_claim_amount` (provisional = lifetime paid; final = lifetime − POSTED TPL offsets − exemptions, floored at 0), `contractor_commission` (3 tiers, round-half-up once per posting, totals = sum of rounded), `hardship_reduction` (FULL = outstanding; PARTIAL = min(requested, max(0, outstanding − max(0, homestead − cap)))).

### PRD-ambiguity adjudications
1. **Settlement-create state gate**: implemented as "an active (FILED/AMENDED) lien exists on the case" rather than literally `status == LIEN_FILED` — required so a second create on a SETTLEMENT_PENDING case yields `ERR_NEGOTIATION_IN_PROGRESS` (priority 8) instead of `ERR_INVALID_STATE_TRANSITION`, matching both corner recipes (`second_open_settlement_rejected`, `settlement_create_temporal_beats_constraint`).
2. **Second lien filing on LIEN_FILED case** returns `ERR_LIEN_ALREADY_EXISTS` (uniqueness), not the generic state error the PRD prose might suggest — ordered as: IDENTIFIED→`ERR_ATTORNEY_NOT_NOTIFIED`, active lien→`ERR_LIEN_ALREADY_EXISTS`, otherwise non-ATTORNEY_NOTIFIED→`ERR_INVALID_STATE_TRANSITION`. Same pattern for `mark-deceased`: the `ERR_ESTATE_CASE_EXISTS` uniqueness check subsumes any member-state check.
3. **Lazy SOL expiry fires only inside the four gated operations** (settlement create/accept, lien amend, posting post), at the priority-7 step after state checks pass — so a lien amend on a RELEASED lien past SOL returns `ERR_LIEN_NOT_AMENDABLE` with no cascade side effects (per `lien_amend_state_beats_sol_temporal`).
4. **Lien amend ordering within priority 7**: negotiation freeze checked before SOL (PRD §3.3 pins "First… Second… Third"), both before cap and OCC.
5. **`requested_reduction_cents` on FULL waivers**: validated (>0) if present, stored as given, never used in the FULL computation ("ignored").
6. **`lifetime_paid_cents` on Member**: stored and serialized (PRD §3.6: "both supplied values are recorded on the member") even though the scaffold's Member field list omits it.
7. **Clock endpoint response**: echoes `to_iso8601` verbatim as `current_utc`; internal clock parses tolerantly (Z, offsets, date-only).
8. **`new_amount_cents` lower bound**: ≥0 (not in the PRD's >0 amount list); negative/non-integer → `ERR_INVALID_REQUEST`.
9. **Reverse of a posting whose lien was never SATISFIED**: lien keeps its current status (no FILED flip), outstanding restored — compensation applies the SATISFIED→FILED transition only when the lien is SATISFIED.

## Step 7: Test-fix loop — 2026-08-14

- Iteration 1: 8-round parallel sweep; 88/89 in every round. Sole failure (all 8 rounds, deterministic): `test_variant_member_net_divergence` — `TypeError: setup_settlement_offered() got an unexpected keyword argument 'medicaid_id'`.
- Diagnosis: STEP 1 PRD covers the asserted rule verbatim (§3.4 member_net_cents formula). STEP 2 test_helpers bug: `setup_settlement_offered` did not accept/forward the `medicaid_id` kwarg that its delegate `setup_case_with_lien` already supports.
- Fix (test_helpers/fixtures.py): added `medicaid_id=None` parameter to `setup_settlement_offered`, forwarded to `setup_case_with_lien`. No implementation changes; no test deletions.
- Iteration 2: 8-round parallel sweep — all 8 rounds 89/89 passed. Clean exit.

## Step 7: Run Tests and Iterate — 2026-08-14T08:05:00.000Z

**Summary**

- **Iterations run:** 2 (sweep 1 found the failure; sweep 2 after the fix passed all 8 rounds at 89/89 each).

- **Tests deleted:** None. The single failing test (`test_variant_member_net_divergence`) asserts the `member_net_cents` formula, which PRD §3.4 covers verbatim ("the member's `member_net_cents` is the `gross_amount_cents` less `fee_amount_cents`, less `litigation_costs_cents`, less `state_recovery_cents`") and uniquely determines — no silence/collapse pattern applied.

- **Fixes applied to `test_helpers/`:** One. `/home/ubuntu/github/CodingPRD/tasks/task_1663_third_party_liability_medicaid_estate/test_helpers/fixtures.py` — `setup_settlement_offered()` gained a `medicaid_id=None` parameter forwarded to `setup_case_with_lien()`. Why: the test `test_variant_member_net_divergence` passed `medicaid_id=None` to this fixture, but the fixture's signature rejected it (`TypeError: got an unexpected keyword argument 'medicaid_id'`), even though its delegate already supports the kwarg. This was a fixture-gap test bug, not an implementation bug — the fix makes the helper chain consistent without touching any assertion.

- **Fixes applied to `implementation/`:** None. The implementation was already PRD-faithful; all 88 other tests passed in every round of the first sweep, and the sole failure was a test-side TypeError before any API call.

Final state: 8/8 parallel rounds green, 89/89 tests passing per round, deterministic (the original failure was identical across all 8 rounds of sweep 1, and the fix is a pure signature-forwarding change with no timing sensitivity).

## Step 8: Finalize PRD — 2026-08-14T08:12:00.000Z

Done. `PRD_FINALIZED.md` is a byte-identical copy of `PRD.md` — 0 edits, which is the correct outcome here.

## Summary

**PRD.md vs PRD_FINALIZED.md:** 305 lines vs 305 lines, 0% delta (byte-identical, verified with `diff -q`).

**Changes:** None.

**Rationale:** The Step 7 diff lists exactly one fix — a `test_helpers/fixtures.py` signature gap where `setup_settlement_offered()` gained a `medicaid_id=None` parameter forwarded to `setup_case_with_lien()`. I verified:

1. The fix is purely test-side. `fixtures.py:163-171` now accepts and forwards `medicaid_id`; `fixtures.py:111-122` (`setup_case_with_lien`) already supported the kwarg. No assertion changed, no implementation file was touched.
2. The sole failing test (`test_04_settlement_negotiation.py:71 test_variant_member_net_divergence`) failed with a `TypeError` before any API call — a fixture bug, not a PRD silence or PRD/impl mismatch.
3. The behavior that test asserts (the `member_net_cents` formula) is pinned verbatim by PRD §3.4 (line 182: "the member's `member_net_cents` is the `gross_amount_cents` less `fee_amount_cents`, less `litigation_costs_cents`, less `state_recovery_cents`") and the implementation matches it exactly (`implementation/services.py:144`: `member_net = gross - fee - costs - state_recovery`, inside `settlement_recovery_amount` at lines 128-145).
4. No tests were deleted and no `implementation/` fixes were applied, so there are no Step 7 items tracing to any PRD-relevant behavioral choice.

**Pre-edit search log:** No edits were made, so no per-edit (a)/(b)/(c) entries exist. The verification searches performed were: reading `test_helpers/fixtures.py` (fixture signatures and forwarding chain), reading `test_suite/test_04_settlement_negotiation.py:60-110` (the failing test's assertions), reading `PRD.md` §3.4 lines 182-186 (`member_net_cents` formula and recompute rules), and reading `implementation/services.py:110-175` (the settlement recovery calculation confirming impl matches PRD verbatim).

File produced: `/home/ubuntu/github/CodingPRD/tasks/task_1663_third_party_liability_medicaid_estate/workspace/PRD_FINALIZED.md`

## Step 9: Complete PRD — 2026-08-14T08:20:00.000Z

All changes verified — 21 modified lines carrying the 24 edits, no other drift. Final summary:

## Summary

**File produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1663_third_party_liability_medicaid_estate/workspace/PRD_COMPLETED.md`

**Source vs output:** PRD_FINALIZED.md 305 lines / 49,759 chars → PRD_COMPLETED.md 305 lines / 52,303 chars (char-delta +2,544; line count unchanged — all edits are inline inserts/revisions, no new sections).

**Counts:** 21 ambiguity-pins, 3 mismatch-revisions (24 changes total across 21 lines; three lines carry two edits each).

**Changes (one bullet each):**

- §2.1 — insert — ambiguity — blank/whitespace `X-User-ID` and unrecognized role strings count as malformed headers — middleware.py:38-48
- §2.3 — insert — ambiguity — out-of-range `limit`/`offset` clamped to [1,100]/[0,∞), non-integer values fall back to defaults — util.py:127-141
- §2.3 — insert — ambiguity — equal `created_at` ties broken by creation (insertion) order — util.py:142, db.py:23-28
- §2.3 — insert — ambiguity — `has_more` = (`offset` + returned items) < `total_count` — response.py:27
- §2.4 — insert — ambiguity — `version` starts at 1 on creation — db.py:75
- §2.5 — revise — ambiguity — clock endpoint accepts any ISO 8601 timestamp (no monotonicity check) and echoes the supplied string verbatim as `current_utc` — clock.py:13-19, util.py:101-114
- §2.5 — insert — ambiguity — `created_at`, `updated_at`, and envelope `api_request_timestamp` also read the logical clock — db.py:64-81, response.py:13
- §2.5 — revise — mismatch — lazy SOL cascade fires only from the four gated operations (after earlier §2.8 checks pass); all other writes never consult the calendar or fire the cascade — services.py:187-217; routes/cases.py:108-226, routes/liens.py:129-138, routes/settlements.py:76-78,203-205, routes/postings.py:119-121
- §2.8 — insert — ambiguity — blank/whitespace strings count as missing; date fields must be valid `YYYY-MM-DD` calendar dates — util.py:30-85
- §3.1 — revise — mismatch — `medicaid_id` recorded without any server-enforced uniqueness; `state_code` recorded without format validation, matched case-sensitively against exactly `MT`/`WY` — members.py:18-28
- §3.2 — insert — ambiguity — body `member_id` naming no registered member → `ERR_NOT_FOUND` (404) — cases.py:39-40
- §3.2 — insert — ambiguity — Feb 29 injury yields Feb 28 `sol_date` — util.py:93-98, cases.py:66
- §3.2 — insert — ambiguity — expense-claim addition is not gated on case status and never fires the §2.5 cascade — cases.py:127-151
- §3.3 — revise — ambiguity — the one-active-lien check fires before the generic later-status error, so refiling on a case at `LIEN_FILED`/`SETTLEMENT_PENDING` yields `ERR_LIEN_ALREADY_EXISTS` — liens.py:43-62
- §3.3 — insert — ambiguity — `new_amount_cents` must be an integer ≥ 0 (zero permitted) — liens.py:115
- §3.4 — revise — mismatch — negotiation opening is gated solely on an active (`FILED`/`AMENDED`) lien; case status is never consulted, so a `SETTLEMENT_PENDING` case (post-acceptance, no live negotiation) can open a fresh negotiation — settlements.py:66-74
- §3.4 — insert — ambiguity — countering requires no active lien; with none, the lien outstanding feeding the formulas is zero — settlements.py:167-169
- §3.5 — insert — ambiguity — posting `lien_id` snapshot is null when no active lien exists at recording — postings.py:57-63
- §3.6 — insert — ambiguity — `lifetime_paid_cents` must be an integer ≥ 0 — members.py:51
- §3.6 — insert — ambiguity — mark-deceased returns the updated Member with 200 OK despite also creating the EstateCase — members.py:84
- §3.6 — insert — ambiguity — file-claim from any non-`OPENED` status → generic `ERR_INVALID_STATE_TRANSITION` — estates.py:64-69
- §3.6 — insert — ambiguity — `exempt_services_cents` must be an integer ≥ 0 — estates.py:59
- §3.7 — insert — ambiguity — `requested_reduction_cents` supplied with a `FULL` application is recorded on the waiver but plays no role in the decision — estates.py:137-144, services.py:179-180
- §3.7 — insert — ambiguity — rescinding a waiver whose approval drove the case to `PAID` restores the balance but leaves the case `PAID` — waivers.py:162-166

**Notable judgment calls:** the three mismatches (SOL cascade scope, member-identifier validation, settlement-open gate) were revised to match impl exactly, including the impl's permissive settlement reopening on `SETTLEMENT_PENDING`. Everything else in the impl (all calculation formulas, tier boundaries, freeze/SOL/estate-deadline boundary semantics, OCC ordering, SoD placement, validation sequencing, error catalog, filters, lifecycle transitions) was already uniquely pinned by PRD_FINALIZED.md and left untouched.
