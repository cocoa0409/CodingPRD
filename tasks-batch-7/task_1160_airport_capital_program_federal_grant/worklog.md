# Worklog — task_1160_airport_capital_program_federal_grant

## Step 1: Create Task Directory — 2026-08-11T05:19:00.000Z

Pre-assigned output folder `tasks/task_1160_airport_capital_program_federal_grant` with `workspace/` subdirectory already existed; Step 1 auto-index scan skipped per instructions. Directory verified present and empty.

## Step 2: Generate Scaffold — 2026-08-11T06:17:00.000Z

All checks pass. The lint verdict block, verbatim:

```
Coverage
  §1.5 endpoints declared:    75
  §1.1 entities declared:     16
  §1.8 instances scanned:     23
  §1.9 instances scanned:     51
  Calls scanned (§1.8+§1.9):  1287

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Summary

**Output files** (all written, YAML-valid, correct top-level key split):
- `/home/ubuntu/github/CodingPRD/tasks/task_1160_airport_capital_program_federal_grant/SCAFFOLD.yaml` — §1.0–§1.7 only (response envelope, entities, state machines, concurrency rules, calculations, validations, endpoints, errors, roles)
- `/home/ubuntu/github/CodingPRD/tasks/task_1160_airport_capital_program_federal_grant/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_1160_airport_capital_program_federal_grant/SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`

**Counts:** 16 entities, 14 state machines, 8 calculations, 75 endpoints, 32 errors, 6 roles, 29 ordered validations, 2 OCC concurrency rules; §1.8 has 23 instances (9 rules × 2–3, exceeding the ≥18 minimum); §1.9 has 51 active instances + 8 `excluded_because` stubs.

**Archetype/difficulty design (per "harder than expert"):** primary `compliance_audit` + secondary `ledger_reconciliation`, flat FK topology, cyclic state-machine shape, `segregation_of_duties` role model (certifier ≠ creator/preparer enforced via X-User-ID on both the assurance and drawdown paths), `entity_backed: Contractor` ownership on invoice/DBE-report creation.

**Notable design decisions:**
- All 8 scenario elements map to entities: CIP + dual-variant priority scoring (sponsor vs federal weights), application + 6 auto-created sponsor assurances gating submit, tiered federal/state/local waterfall funding split, DBE goal adjudication with a depth-3 withhold cascade (report → contract posture → invoice WITHHELD → ledger recompute), construction phases with two *different* overlap semantics (half-open adjacency-allowed on AirfieldFacility vs mandatory 24h buffer on Contractor), invoice retainage + per-line-rounded drawdown, closeout with audit-finding gating and a depth-3 close cascade (grant → contracts → invoices + retainage release), and useful-life disposal with asset-kind-selected payback variants (straight-line vs FMV).
- Two pinned trap calculations: per-line-round-then-sum drawdown (90,000.00 vs 89,999.99 divergence proven) and the circular contingency-on-new-total amendment formula (algebraically resolved, 1,222,222.22 / 122,222.22 / 200,000.00).
- Logical clock endpoints `/_clock/set_current_utc` (default `2026-05-01T00:00:00Z`) and `/_ops/run_checkpoint` drive deadline expiry, useful-life accrual, and phase-window activation deterministically.
- Every numeric assertion in all 74 recipes was pre-computed and verified with a Decimal/half-up script (scores, retainage, per-line rounding, amendment math, tier splits, boundary values 819,000.00 vs 819,000.02, DBE 12.50 vs 12.49, disposal paybacks 40,000.00/108,000.00/0.00, day-count floors, and the grant/NPE conservation invariant ending at NPE 4,919,000.00).
- No sibling task directories were inspected; the scaffold was built purely from the scenario text plus the skill spec and its lint/reference files.

## Step 3: Copy Shared Files — 2026-08-11T06:18:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `tasks/task_1160_airport_capital_program_federal_grant/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-11T06:31:00.000Z

PRD generation complete. Summary:

**Output file:** `/home/ubuntu/github/CodingPRD/tasks/task_1160_airport_capital_program_federal_grant/workspace/PRD.md`
**Size:** 336 lines, 7,997 words

**Section list:**
- §1 Introduction (2 paragraphs — AIP business context + system scope/clock)
- §2 Global Specifications (10 subsections): 2.1 RBAC, 2.2 API Response Structure (verbatim fixed block), 2.3 Pagination, 2.4 Logical Clock & Federal Fiscal Calendar, 2.5 Common Resource Properties & Identifiers, 2.6 Monetary Precision, 2.7 Optimistic Concurrency Control, 2.8 Cascading State Reconciliation, 2.9 Nested Retrieval & Validation Order, 2.10 Segregation of Duties
- §3 Business Logic (9 subsections): 3.1 Sponsors/Facilities/CIP lifecycle, 3.2 Priority Scoring & Selection Sweep, 3.3 Application→Award incl. assurances, 3.4 Grant Ledger/Funding Split/Amendments, 3.5 Contractors/Contracts/Invoicing, 3.6 DBE Reporting & Withholding, 3.7 Reimbursement Drawdowns, 3.8 Construction Phasing, 3.9 Closeout/Audit/Asset Disposal
- §4 Endpoint Definitions (75-row table, 4 columns)
- §5 Error Code Catalogue (32 rows, 2 columns)

**Scaffold-rule coverage (all confirmed):**
- **Entities (16):** all fields covered in backticked prose; the three `common_fields: false` entities (SponsorAssurance, DBEReport, AuditFinding) explicitly noted as carrying only `id`/`created_at`.
- **State machines (14, all transitions):** from/to pairs, preconditions with error IDs, and side effects all expressed (including cyclic CIP amendment loop, application resubmit loop, invoice DBE withhold/release cycle, asset return-to-service loop).
- **Calculations (8):** both `cip_priority_score` variants (weights, doubling, +5 bonus, −10 penalty, cap/floor, rank tie-break by `created_at`), funding-split waterfall (75/80/90/95% tiers, 50% state of non-federal), pinned per-line drawdown rounding (with rejected sum-first example), amendment contingency release (base ÷ 0.9 pinned order), retainage split, DBE attainment (inclusive threshold on rounded value), both disposal-payback variants (straight-line vs fair-market using grant's current `federal_share_pct`, zero-remaining-years → 0.00), closeout final settlement (chronological replay, `min(released, entitlement_portion)` NPE credit, sponsor-local payment note).
- **Validations (29, priority-ordered):** global evaluation order stated in §2.9; explicit in-endpoint orderings given for application submit (5 checks), phase creation (5 checks), invoice verify (3), drawdown submit (3) and approve (2), amendment approve (2), project drop (2), contract award; every check paired with its exact `error_id`; all `applies_to` scopes enumerated.
- **OCC (2 rules):** `expected_grant_version` on amendment creation and `expected_program_version` on apply-selection, both rejected with `ERR_STALE_VERSION` (412); no race framing; all other endpoints explicitly take no version field.
- **Endpoints (75) and errors (32):** all present in §4/§5 tables; every error ID also mentioned in §2/§3 prose; all 6 roles with exact spelling and per-role identity translation (Contractor entity-backed, five opaque).

**Hard contract reports:**
- Field coverage: 100 required (entities + request bodies + query params), 100 present, 0 missing — **PASS**
- Rule coverage: validations with priority 29/29 expressed; OCC 2/2; transitions 52/52; calculations 8/8; validation conditions 29/29 matchable to error IDs; side effects/applies_to all expressed; field structured content reconstructible; sibling branches symmetric — **PASS**
- §3 path purity: 562 backtick tokens scanned, 0 path tokens, 0 bare HTTP methods, 0 method+path combos — **PASS**

The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened or referenced. PRD.md ends at §5 with no audit footer.

## Step 5: Generate Unit Tests — 2026-08-11T06:55:00.000Z

Generation complete. All quality gates pass.

## Summary

**Files created** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1160_airport_capital_program_federal_grant/`):

- `test_helpers/` — `__init__.py` (barrel), `types.py` (16 entity TypedDicts — lean `SponsorAssurance`/`DBEReport`/`AuditFinding` omit `updated_at`/`version`, 25 enums), `api_client.py` (79 methods, one per PRD §4 endpoint), `api_errors.py` (32 error IDs + HTTP map registered with the framework), `assertions.py` (per-entity asserts + `assert_money` + grant/asset conservation invariants), `factories.py` (input-fields-only, auto-unique `loc_id`), `constants.py` (funding-split tiers, score weights, contingency, phase limits), `test_users.py` (6 role headers with stable SoD operator IDs + `make_contractor_headers` for the entity-backed Contractor), `fixtures.py` (5 tiers: clock/checkpoint drivers, entity chains, certified-application assembly, `setup_active_grant`, contract/invoice/DBE/drawdown lifecycles, asset/phase helpers, under-audit/closed-grant terminal states)
- `test_suite/` — `conftest.py` + 11 test files: `test_01_sponsors_programs_projects.py`, `test_02_priority_scoring_selection.py`, `test_03_applications_assurances.py`, `test_04_grant_funding_amendments.py`, `test_05_contracts_invoices.py`, `test_06_dbe_compliance.py`, `test_07_drawdowns.py`, `test_08_closeout_audit.py`, `test_09_assets_disposal.py`, `test_10_construction_phases.py`, `test_11_security_and_operations.py`

**Test counts:** 97 total — **Queue A: 46** (23 difficulty instances × 2 tests each), **Queue B: 51** (51 non-stub corner instances × 1 each).

**Skipped instances:** none. All 74 non-stub instances passed the PRD-first two-condition filter — every asserted rule (dual score variants, funding waterfall, per-line drawdown rounding, circular contingency, both OCC guards, DBE/closeout cascades, phase overlap/buffer geometry, closeout settlement/NPE credit) has verbatim PRD prose coverage and a uniquely-derived outcome. Version assertions are written as relative +1 increments where PRD does not pin the absolute initial version. The 8 `excluded_because:` stubs in the corner `errors` section were not translated (per spec); all 8 cross-references verified to resolve to real §1.8 instances.

**Stage-check results:**
- Compile + import of `test_helpers`: OK
- `pytest --collect-only`: 97 tests collected
- C4 audit: every docstring ends with exactly one `Design:` line resolving to a real instance; difficulty coverage 23/23 (≥2 each), corner coverage 51/51 (≥1 each)
- C1 verbatim pass: 133/133 quoted citation segments survive whitespace-normalized literal match against PRD.md (2 initially failed — markdown-bold markers and elided quote — fixed)
- No `skip`/`skipif`/`xfail` marks; no scaffold references in generated code; all test imports resolve against `test_helpers`

## Step 6: Generate Implementation — 2026-08-11T06:55:00.000Z

Implementation complete and verified. Summary:

## Files created (all under `/home/ubuntu/github/CodingPRD/tasks/task_1160_airport_capital_program_federal_grant/workspace/implementation/`)

- `start.sh` — foreground launcher; guarded dep install (`python3 -c "import flask"` check so per-test reboots skip pip), `exec python3 app.py`
- `requirements.txt` — flask>=3.0,<4.0
- `app.py` — Flask entrypoint, blueprint registration, envelope-wrapped error handlers (ApiError, HTTPException, 500 fallback)
- `store.py` — in-memory `DB` singleton: 16 entity dicts, grant-number sequence counters, logical clock (default `2026-05-01T00:00:00Z`), monotonic timestamp generator
- `errors.py`, `util.py`, `auth.py` — ApiError factory, Decimal money helpers (`r2` round-half-up), envelope/pagination, `X-User-ID`/`X-User-Role` auth + per-endpoint RBAC decorator
- `domain.py` — all calculations (dual-variant priority scores, funding-split waterfall, per-line drawdown rounding, amendment contingency `base/0.9` resolution, retainage split, DBE attainment, disposal payback variants, closeout settlement), cascades (selection sweep, drop scrub, DBE withhold/release, closeout depth-3, checkpoint expiry), and 16 serializers matching the scaffold field-for-field
- `routes/` — `ops.py`, `sponsors.py`, `programs.py`, `applications.py`, `grants.py`, `contracts.py`, `drawdowns.py`, `closeout.py`, `phases.py`

## Endpoint count: 75
Confirmed via Flask's url_map (76 registered rules minus Flask's built-in `/static` catch-all). All PRD §4 routes implemented with the exact roles, status codes, filters, and validation-priority ordering from the scaffold.

## Boot contract confirmed
`bash start.sh` from `implementation/` boots in ~3s, binds `0.0.0.0:$PORT` (tested on 5 ports including 3 concurrent boots), and state fully wipes on re-invocation (verified: create sponsor, kill, reboot → list empty). No seeding anywhere — the store starts empty.

## Verification performed
Two smoke suites (60+ assertions) passed against fresh boots, covering: envelope shape and pagination meta; 401/403/404 precedence with entity-named messages; OCC 412 on both guarded writes; priority scoring both variants (safety doubling, multi-airport bonus, federal penalty, cap/floor) with rank tie-break by created_at; prefix selection sweep; assurance SoD and completeness gate; offer/accept with entitlement/debit math and `AIP-<loc>-<fy>-<seq>` grant numbers; funding waterfall; invoice verify cap with equality boundary and reject exclusion; drawdown per-line rounding, SoD, return-and-recertify loop, approve cascade; DBE shortfall/compliance withhold-release cascades; phase duration/overlap/buffer checks and activation window; asset service credits, EQUIPMENT straight-line and LAND fair-market paybacks, `ERR_FMV_REQUIRED`; closeout blockers (phases/findings/disposals), final settlement with NPE release, contract/invoice/retainage cascade; checkpoint program+application expiry with project-drop cascade; amendment supersede/approve/reject with NPE debits and waterfall recompute.

One spec reconciliation worth noting: the scaffold's `invoiced_total` static definition (includes SUBMITTED) conflicts with its own verify side-effect and the reject-no-side-effect rule; I implemented the operationally consistent reading — `invoiced_total`/`retainage_held` cover VERIFIED|INCLUDED|PAID — which is the only interpretation under which the 402 equality boundary and reject flow both behave sanely.

## Step 7: Run Tests and Iterate — 2026-08-11T07:16:00.000Z

**Summary**

- **Iterations run:** 1 (single 8-round parallel stability sweep; all 8 rounds ran to completion concurrently with per-test-server isolation).
- **Results:** Round 1: 97/97; Round 2: 97/97; Round 3: 97/97; Round 4: 97/97; Round 5: 97/97; Round 6: 97/97; Round 7: 97/97; Round 8: 97/97. Zero failures, zero errors, zero skips across all 776 test executions.
- **Tests deleted:** none — the failing-test union across all 8 rounds was empty, so no PRD-coverage or unique-derivability deletions were needed.
- **Fixes applied to `test_helpers/`:** none.
- **Fixes applied to `implementation/`:** none.

The implementation at `/home/ubuntu/github/CodingPRD/tasks/task_1160_airport_capital_program_federal_grant/workspace/implementation/` (Flask app, 75 endpoints, in-memory store) passes the full 97-test suite stably under 8x concurrent load, including the pinned calculations (per-line drawdown rounding 90,000.00 vs 89,999.99, amendment contingency 1,222,222.22/122,222.22/200,000.00, funding waterfall tiers, DBE inclusive boundary, both disposal-payback variants), both OCC guards, all cascades (DBE withhold/release, closeout depth-3, checkpoint expiry), and the SoD/RBAC matrix. Step 7 is complete; no further iteration required.

Orchestrator note: pre-sweep route-parity check confirmed the implementation registers exactly the 75 (method, path) route pairs declared in SCAFFOLD.yaml — 0 missing, 0 extra. All 8 `results.{1..8}.json` files verified on disk with passed == total == 97.

## Step 8: Finalize PRD — 2026-08-11T07:17:00.000Z

SKIPPED per skip condition: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — PRD.md already determined every behavior the implementation exhibits.

## Step 9: Complete PRD — 2026-08-11T07:25:00.000Z

PRD_COMPLETED.md is complete: 338 lines / 61,840 chars vs PRD.md's 336 lines / 58,772 chars (+2 lines, +3,068 chars).

## Summary

**Source vs output:** `workspace/PRD.md` (336 lines, 58,772 chars) → `workspace/PRD_COMPLETED.md` (338 lines, 61,840 chars). Char-delta: +3,068. No sections added or removed; all changes are inline sentence inserts/revisions.

**Counts:** 12 ambiguity-pins (inserts), 2 mismatch-revisions.

**Changes:**

- §2.1 — insert — ambiguity — Contractor ownership comparison runs only after the referenced contract resolves; unresolvable reference yields ERR_NOT_FOUND before any ownership check — implementation/routes/contracts.py:152-155, 231-234
- §2.2 — insert — ambiguity — Undefined paths/unsupported methods answered through the error envelope with `ERR_NOT_FOUND`; malformed/non-JSON body treated as empty object (so required-field failures surface as ERR_VALIDATION); unexpected internal failure → `ERR_INTERNAL` HTTP 500 — implementation/app.py:26-36, util.py:104-105
- §2.3 — insert — ambiguity — Non-numeric `limit`/`offset` fall back to defaults; out-of-range numerics clamped (limit into [1,100], negative offset to 0) rather than rejected — implementation/util.py:181-192
- §2.4 — insert — ambiguity — Clock-set response `current_utc` echoes the supplied `to_iso8601` string verbatim (no normalization) — implementation/routes/ops.py:14-20
- §2.5 — insert — ambiguity — Resource timestamps drawn from the logical clock via a monotonic non-decreasing generator (+1ms when needed), not the wall clock — implementation/util.py:57-63
- §2.5 — insert — ambiguity — `version` starts at 1 at creation for all common-field resources — implementation/util.py:72-80
- §3.1 — revise — mismatch — `npe_entitlement_available` pinned as a running ledger (debited at acceptance/amendment, credited at closeout only by min(released, entitlement_portion)); the closed-form "total minus sum over non-CLOSED grants" holds only while all grants are non-CLOSED — entitlement drawn into by a closed grant stays consumed — implementation/domain.py:224-231, routes/applications.py:202-203, routes/grants.py:159-163
- §3.3 — insert — ambiguity — Supplied `discretionary_amount` must be a number ≥ 0, else ERR_VALIDATION — implementation/routes/applications.py:148-154
- §3.3 — insert — ambiguity — Accept-offer responds 200 with the updated application object (grant reachable via `created_grant_id`) — implementation/routes/applications.py:204-207
- §3.4 — insert — ambiguity — `grant_number` `<seq>` is a per-(`loc_id`, `fiscal_year`) counter starting at 1 — implementation/routes/applications.py:184-192
- §3.4 — insert — ambiguity — `federal_share_pct` wire representation is a JSON-number fraction of 1 (0.75/0.80/0.90/0.95) — implementation/domain.py:366
- §3.5 — revise — mismatch (the known reconciliation) — `invoiced_total` sums `gross_amount` over VERIFIED|INCLUDED|PAID only; SUBMITTED is excluded alongside REJECTED/WITHHELD (PRD previously included SUBMITTED, which would double-count in the verify cap) — implementation/domain.py:162-179 (ledger_recompute), routes/contracts.py:290-294
- §3.6 — insert — ambiguity — Adjudication evaluates the report's PENDING precondition (ERR_INVALID_STATE) before the contract's AWARDED gate (ERR_CONTRACT_CLOSED) — implementation/routes/contracts.py:193-199
- §3.8 — insert — ambiguity — Contractor 24-hour rest buffer is evaluated only against phases in PLANNED or ACTIVE (completed/cancelled phases impose no buffer), matching the overlap check's status filter — implementation/routes/phases.py:58-65
- §3.9 — insert — ambiguity — Asset elapsed years floored at zero (in_service_date at/after the clock → 0 elapsed) — implementation/domain.py:79-83
- §3.9 — insert — ambiguity — Supplied `fair_market_value` (either asset kind) must be a number ≥ 0 else ERR_VALIDATION; ignored by the EQUIPMENT payback variant — implementation/routes/closeout.py:136-143

Everything else walked (all 51 endpoints, both OCC guards, all state machines, selection-sweep scoring/ranking/scrubbing, drawdown per-line rounding, closeout settlement cascade, checkpoint batch, serializers, filters, RBAC table, error catalogue) was already uniquely pinned by PRD prose and required no change.
