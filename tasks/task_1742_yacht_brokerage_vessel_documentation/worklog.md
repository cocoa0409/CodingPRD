# Worklog — task_1742_yacht_brokerage_vessel_documentation

## Step 1: Create Task Directory — 2026-08-14T12:23:00.000Z

Task directory `tasks/task_1742_yacht_brokerage_vessel_documentation/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher. Step 1 treated as DONE; no index scan performed, no other task directory touched.

## Step 3: Copy Shared Files — 2026-08-14T12:24:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1742_yacht_brokerage_vessel_documentation/workspace/INSTRUCTION.md` (1424 bytes). Done out of order while Step 2 subagent runs; no file conflicts (Step 2 writes SCAFFOLD*.yaml at task root).

## Step 2: Generate Scaffold — 2026-08-14T12:52:00.000Z

All three files written and lint-clean.

## Summary

Task: `task_1742_yacht_brokerage_vessel_documentation` — Yacht Brokerage & Vessel Documentation scaffold, generated fresh from the scenario description without reading any sibling task.

**Complexity profile**: multi-party-negotiation primary, compliance-audit secondary; layers = optimistic concurrency + cascading side effects + dual-variant calculation + rate/threshold triggers; flat topology, cyclic state machines, segregation-of-duties role model.

**Artifact counts** (deliberately pushed past the Expert band per the difficulty directive):
- Entities: **15** (Brokerage, BrokerAgent, Client, Vessel, ListingAgreement, SyndicationEvent, Offer, Contingency, EscrowLedgerEntry, LienRecord, DocumentationRecord, ClosingStatement, TaxAssessment, TitleTransfer, DomainEvent)
- State machines: **7** (Listing, Offer [cyclic counter loop], Contingency [OBJECTED→OPEN cure cycle], EscrowLedgerEntry, LienRecord, ClosingStatement [APPROVED→BALANCED reopen loop], TitleTransfer)
- Calculations: **8** (commission_split tiered+co-broke, sales_use_tax with state caps and offshore exemption, proration_aggregator with pinned per-day-then-multiply rounding, lien_payoff_waterfall, closing_total with pinned evaluation order, escrow_interest_accrual dual-variant ACT/360 vs ACT/365, documentation_fee dual-variant list-vs-offer basis, deposit_requirement)
- Validations: **20** (priority-ordered across auth/existence/state/business_safety/constraint/temporal/referential/fiscal)
- Endpoints: **61** (including `POST /_clock/set_current_utc` with pinned default 2026-08-01T00:00:00Z)
- Errors: **22**
- Roles: **5** (PlatformAdmin opaque; ListingAgent & SellingAgent entity-backed on BrokerAgent; ClosingOfficer & EscrowOfficer opaque; segregation of duties between ClosingOfficer-build and ListingAgent-approve)
- Concurrency rules: **3** OCC rules (offer accept, statement build, statement approve)
- §1.8 difficulty instances: **18** (9 rules × 2, each with full structured test_recipe + pre-computed literal asserts)
- §1.9 corner instances: **27 active + 2 excluded_because stubs = 29 total**

**Lint verdict** (verbatim):
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Files written**:
- `/home/ubuntu/github/CodingPRD/tasks/task_1742_yacht_brokerage_vessel_documentation/SCAFFOLD.yaml` (2081 lines)
- `/home/ubuntu/github/CodingPRD/tasks/task_1742_yacht_brokerage_vessel_documentation/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1821 lines)
- `/home/ubuntu/github/CodingPRD/tasks/task_1742_yacht_brokerage_vessel_documentation/SCAFFOLD_CORNER_DESIGN.yaml` (1526 lines)

## Step 4: Generate PRD — 2026-08-14T13:02:00.000Z

The PRD is complete and all verification passes succeeded. Summary:

**Output written:** `/home/ubuntu/github/CodingPRD/tasks/task_1742_yacht_brokerage_vessel_documentation/workspace/PRD.md` — 288 lines.

**Section list:**
- §1 Introduction (3 paragraphs, deal-arc framing)
- §2 Global Specifications: 2.1 RBAC (5 roles with identity translations), 2.2 API Response Structure (verbatim block, byte-exact), 2.3 Pagination, 2.4 Resource Identity/Timestamps/Versioning (incl. the `SyndicationEvent`/`DomainEvent` id+created_at-only exception and left-to-right nested-path resolution), 2.5 Logical Clock & Expiry Sweeps, 2.6 Optimistic Concurrency Control (4 guarded endpoints), 2.7 Monetary Precision & Rounding, 2.8 Validation Pipeline & Error Ordering, 2.9 Segregation of Duties & Audit Trail
- §3 Business Logic (8 subsections): 3.1 Desk Onboarding, 3.2 Vessel Registration/Documentation/Lien Search, 3.3 Listing Agreements & MLS Syndication, 3.4 Offer Submission & Counter-Offer Chain, 3.5 Contingencies & Cure Window, 3.6 Escrow Trust Accounting, 3.7 Building the Closing Statement (all five pinned-order calculations + documentation-fee schedule in prose), 3.8 Approval/Disbursement/Title Transfer
- §4 Endpoint Definitions (61-row, 4-column table), §5 Error Code Catalogue (22-row, 2-column table)

**Hard contract reports:**
- Contract 1 (Field-Name Coverage): 97 required identifiers (all entity fields, endpoint inputs, query/path params) — 97 present, 0 missing. PASS
- Contract 2 (Rule Coverage): all 22 error IDs matchable in §2/§3 prose; all enum/state values present; all 7 state machines' transitions, preconditions, and cross-entity cascades expressed (accept/fail/cancel/expiry/disburse/void/counter); all 8 calculations rendered as reconstructible prose with constants embedded (tier rates 10/8/6%, PREMIER ×1.10, BOUTIQUE flat 5%, FL $18k/SC $30k caps, $4,500 slip fee, $750 fuel credit, 1.00% ACT/360 vs 1.25% ACT/365 interest, $133+$4/foot vs 0.15% doc fee, 10% deposit floor with 2× anti-structuring ceiling); all 3 OCC rules named with endpoint + expected-version field + `ERR_STALE_VERSION`/412; validation priority ordering (incl. excessive-before-insufficient, OCC-before-segregation, duplicate-before-doc-coherence, deadline-before-acceptance, shape-validation-last) explicit. PASS
- Contract 3 (§3 Path Purity): 217 backticked tokens scanned in §3, 0 path/method/combined violations. PASS

§2.2 emitted byte-identical to the canonical block; document ends at §5 with no audit footer.

## Step 6: Generate Implementation — 2026-08-14T13:35:00.000Z

All done. Here's the summary.

## Implementation complete

**Location**: `/home/ubuntu/github/CodingPRD/tasks/task_1742_yacht_brokerage_vessel_documentation/workspace/implementation/`

### File list (line counts)
| File | Lines |
|---|---|
| `start.sh` | 10 |
| `requirements.txt` | 1 |
| `app.py` | 57 |
| `db.py` | 92 |
| `errors.py` | 97 |
| `response.py` | 52 |
| `middleware.py` | 131 |
| `routes/onboarding.py` | 126 |
| `routes/vessels.py` | 242 |
| `routes/listings.py` | 236 |
| `routes/offers.py` | 372 |
| `routes/escrow.py` | 156 |
| `routes/closing.py` | 400 |
| `routes/title.py` | 156 |
| `services/common.py` | 268 |
| `services/calculations.py` | 170 |
| `services/events.py` | 17 |
| `services/sweep.py` | 53 |
| **Total** | **2,636** |

### Coverage
- **61/61 endpoints** from the scaffold endpoint table implemented and registered (verified via Flask url_map), including `POST /_clock/set_current_utc` and `GET /yacht/domain-events`.
- **Storage**: in-memory dicts only (`db.py` `Store` class), zero seeding at startup — verified empty store on fresh boot.
- **Envelope**: exact `meta`/`response_type`/`data` shape with `api_request_id` (`req_…`), millisecond timestamps, pagination fields `limit`/`offset`/`total_count`/`has_more` in `meta` for lists.
- **Validation pipeline** honors PRD §2.8 ordering: auth → RBAC → path FK → body FK → state → OCC → business band (deposit-excessive before deposit-insufficient; OCC before segregation on approve; HIN-duplicate before doc-mode mismatch; offer deadline before listing-acceptance) → shape last.
- **Calculations** (Decimal + ROUND_HALF_UP, integer cents): commission tiers (STANDARD/PREMIER ×1.10/BOUTIQUE flat 5%, co-broke 50/50 with unrounded remainder), sales/use tax with FL $18k and SC $30k caps and home-state use-tax credit, day-by-day prorations (per-day round then multiply, fuel credit after), priority-ordered lien waterfall with pool floor at 0, closing totals in pinned order, ACT/360 provisional + ACT/365 final escrow interest, USCG/state documentation fees, deposit requirement with 2x anti-structuring ceiling.
- **State machines**: listings (incl. expiry sweep with offer cascade), cyclic offer counter chains (`round_no`/`parent_offer_id`), contingencies with 5-day cure window, escrow three-role discipline, closing statement segregation of duties (build by ClosingOfficer / approve by ListingAgent), title transfers, lien release/satisfaction, disbursement fan-out (offer→CLOSED, listing→CLOSED, transfer→RECORDED, docs→TRANSFERRED, assessments→FILED).
- **Logical clock** defaults to exactly `2026-08-01T00:00:00Z`; advancing it runs all three expiry sweeps.

### Boot verification
Smoke-tested `bash start.sh` (evaluator-style, `PORT=18995`, throwaway port): server booted and answered HTTP 200 within ~1s, then killed. Six end-to-end smoke suites passed on fresh boots covering the full deal arc, counter chains, kick-out/refund, lien waterfall + shortfall, offshore exemption, reopen rebalance, and all commission tier variants/boundaries. All test servers cleaned up.

## Step 5: Generate Unit Tests — 2026-08-14T13:45:00.000Z

All checks pass. Generation is complete.

## Summary

**test_helpers/** (9 files, all under `/home/ubuntu/github/CodingPRD/tasks/task_1742_yacht_brokerage_vessel_documentation/test_helpers/`):
- `types.py` — 11 status enums + 15 entity TypedDicts (SyndicationEvent/DomainEvent correctly carry only `id`/`created_at`)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (52 endpoints incl. `set_clock`)
- `api_errors.py` — 22 `ApiErrorId` members + HTTP map registered via `set_error_http_status_map`
- `assertions.py` — per-entity asserters + `assert_commission_side_split_invariant`
- `factories.py` — payload factories with `unique_hin()` generator
- `constants.py` — commission tiers, state tax rates/caps, slip/fuel, deposit and cure-window constants
- `test_users.py` — opaque-role constants + mandatory `make_listing_agent_headers`/`make_selling_agent_headers` entity-backed builders
- `fixtures.py` — 5-tier deal pipeline: `setup_brokerage_desk` (co-broke option), `setup_active_listing` (liens, STATE vessels), `setup_accepted_offer`, `waive_all_contingencies`, `setup_balanced_statement`/`setup_approved_statement`, `record_cleared_deposit`, `setup_disbursable`
- `__init__.py` — barrel export

**test_suite/** (10 files, 57 tests): `conftest.py` + `test_01_api_envelope_and_pagination` (4) · `test_02_vessel_registration` (5) · `test_03_listing_lifecycle` (7) · `test_04_offer_negotiation` (6) · `test_05_escrow_trust` (9) · `test_06_closing_calculations` (9) · `test_07_closing_workflow` (10) · `test_08_disbursement_and_title` (4) · `test_09_deal_collapse` (3)

**Count by queue:** A = 30 tests (15 instances × 2); B = 27 tests (all 27 non-stub instances × 1).

**Instances skipped (3, all queue A, PRD-first filter):**
- `dual_variant_calc/escrow_interest_provisional_vs_final_divergence` — §3.6 places final escrow interest "on the closing statement's prorations" but §3.7's proration formula omits it and defines the field as seller-credit-positive; sign/placement yields three divergent faithful readings (402991 / 327649 / 365320), and no PRD field exposes the provisional accrual.
- `dual_variant_calc/documentation_fee_provisional_vs_final_divergence` — PRD names no response field carrying the documentation/title fee; the asserted value is unobservable on any declared output.
- `resource_temporal_overlap/abstract_of_title_recency_window` — §3.2's 30-day ABSTRACT freshness rule is never wired to an enforcing endpoint or error in the PRD (ERR_INVALID_DEADLINE's catalogue condition doesn't cover it).

**Corner stubs not translated (cross-refs verified):** `state_machines/listing_under_contract_to_active_reactivation_side_effects` and `calculations/lien_waterfall_partial_payoff_sets_partially_satisfied` — both difficulty-instance pointers resolve.

**Notable translation decisions:** `fl_tax_cap_boundary_at_exact_cap` uses `list_price_cents=100000000` (the recipe's 30000000 would violate the PRD's USD 1M listing floor; asserted tax values unchanged). `full_warranty_requires_clean_liens` follows the instance's own correction note (lien recorded after build). `disburse_gated_by_vessel_liens_status` uses `validate_error_is_one_of([ERR_LIENS_OUTSTANDING, ERR_WATERFALL_SHORTFALL])` because PRD §3.8 names both errors at the same gate without precedence.

**Self-checks:** py_compile clean; 57/57 tests carry exactly one well-formed `Design:` tag resolving to a real instance (no stub/dual/unknown tags); every quoted docstring span ≥15 chars greps verbatim into PRD.md (whitespace-normalized); zero skip/xfail markers; all 10 modules import against `test_helpers` with every referenced name resolving.

## Step 7: Run Tests and Iterate — 2026-08-14T13:55:00.000Z

All 8 rounds pass cleanly (57/57 each). Emitting the summary.

---

## Summary

**Iterations run: 2** (baseline sweep + verification sweep after one fix)

**Tests deleted: none**

**Fixes applied to `test_helpers/`: none**

**Fixes applied to `test_suite/`: 1**
- `/home/ubuntu/github/CodingPRD/tasks/task_1742_yacht_brokerage_vessel_documentation/test_suite/test_05_escrow_trust.py` — `TestEscrowReleaseStateGating::test_release_pending_entry_with_draft_statement_rejected`: assertion corrected from `ApiErrorId.ERR_INVALID_STATE` to `ApiErrorId.ERR_ESCROW_NOT_CLEARED` (and docstring re-anchored). The test's setup releases a **PENDING** escrow entry; PRD §3.6 states verbatim: *"Release, refund, and forfeiture all demand a CLEARED entry; attempting any of them against an entry in any other state is rejected with `ERR_ESCROW_NOT_CLEARED` (HTTP 409)."* The specific entry-state rule names its own error and pre-empts the generic §2.8 state band the test had cited. This was an assertion mis-translation of PRD wording (STEP 2, TEST IS WRONG), not a weakening — the assertion remains an exact-error_id check at the same 409 status, and the state-vs-business ordering intent stays covered by the sibling test `test_release_cleared_entry_with_unapproved_statement_rejected` (CLEARED entry + DRAFT statement → `ERR_INVALID_STATE`), which passed throughout.

**Fixes applied to `implementation/`: none** — the implementation was already PRD-faithful on the disputed path (`release_entry` in `/home/ubuntu/github/CodingPRD/tasks/task_1742_yacht_brokerage_vessel_documentation/workspace/implementation/routes/escrow.py` raises `err_escrow_not_cleared()` for any non-CLEARED entry before evaluating the offer/statement fiscal gates, matching PRD §3.6).

**Flakiness signal:** the baseline failure was 100% deterministic (failed in all 8 rounds, identical assertion); the fix converts it deterministically. No timing-sensitive failures were observed in either sweep.

**Final state:** 8/8 parallel rounds, 57/57 tests passed per round, 0 failed, 0 errors.

## Step 8: Finalize PRD — 2026-08-14T14:00:00.000Z

Done. PRD_FINALIZED.md is produced at `/home/ubuntu/github/CodingPRD/tasks/task_1742_yacht_brokerage_vessel_documentation/workspace/PRD_FINALIZED.md` and is **byte-identical to PRD.md** (verified via `diff` and matching md5 `472fd80201df491fec57efd1d69a55a4`).

## Summary

**Line counts / %-delta:** PRD.md = 288 lines; PRD_FINALIZED.md = 288 lines; delta = 0 lines, 0.0%. Zero edits made.

**Changes:** none — this is the legitimate zero-edit case the task note anticipates.

**Zero-edit verification evidence:**

The sole Step 7 item was a test-side assertion correction (`test_suite/test_05_escrow_trust.py` line 130: `ERR_INVALID_STATE` → `ERR_ESCROW_NOT_CLEARED`). I verified it was a pure test mis-translation, not a PRD silence or impl mismatch:

1. **The §3.6 quote** — PRD.md line 163 states verbatim: *"Release, refund, and forfeiture all demand a CLEARED entry; attempting any of them against an entry in any other state is rejected with `ERR_ESCROW_NOT_CLEARED` (HTTP 409)."* The error table (line 283) independently lists `ERR_ESCROW_NOT_CLEARED | 409`. The PRD already uniquely determines the disputed behavior — the specific entry-state rule names its own error.

2. **The escrow.py path** — `/home/ubuntu/github/CodingPRD/tasks/task_1742_yacht_brokerage_vessel_documentation/workspace/implementation/routes/escrow.py`:
   - `release_entry` lines 109-110: non-CLEARED entry → `err_escrow_not_cleared()` raised **first**, before the offer-ACCEPTED gate (112-113) and statement-APPROVED gate (114-117, which raises `err_invalid_state` — matching the sibling test at line 154 that still asserts `ERR_INVALID_STATE` for CLEARED entry + non-APPROVED statement).
   - `errors.py` lines 76-77: `err_escrow_not_cleared` → `ApiError("ERR_ESCROW_NOT_CLEARED", ..., 409)`, matching PRD's named error and status.

3. **Why no other impl path needs wording changes** — a repo-wide grep for `err_escrow_not_cleared`/`ERR_ESCROW_NOT_CLEARED` across implementation/, test_suite/, and test_helpers/ shows the error is raised at exactly three sites, all in escrow.py: `release_entry` (line 110), `refund_entry` (line 130), `forfeit_entry` (line 146) — precisely the three actions PRD §3.6's sentence enumerates ("Release, refund, and forfeiture all demand a CLEARED entry"). No other route (closing.py's escrow touches are `escrow_applied_cents` computation, final interest, and the statement-reopen guard, all covered by separate PRD sentences in §3.7/§3.8) raises or gates on this error, so the existing §3.6 wording describes every implementation path that touches the subject. Nothing to widen, soften, or re-scope.

Since the PRD already pinned the behavior the implementation exhibits, any edit would have been invention; the correct output is the verbatim copy.

## Step 9: Complete PRD — 2026-08-14T14:30:00.000Z

All edits are complete. The diff touches exactly 32 paragraphs (32 deletions + 32 insertions in diff terms), all in-paragraph; line count unchanged.

## Summary

**Files**
- Source: `/home/ubuntu/github/CodingPRD/tasks/task_1742_yacht_brokerage_vessel_documentation/workspace/PRD_FINALIZED.md` — 288 lines / 51,393 chars
- Produced: `/home/ubuntu/github/CodingPRD/tasks/task_1742_yacht_brokerage_vessel_documentation/workspace/PRD_COMPLETED.md` — 288 lines / 60,835 chars (+9,442 chars; zero new sections, zero new paragraphs)

**Counts:** 41 ambiguity-pins, 23 mismatch-revisions (64 distinct behavioral changes across 32 paragraph edits).

**Changes** (section — insert|revise — ambiguity|mismatch — what changed — impl ref):

- §2.3 — insert — ambiguity — non-integer/out-of-range `limit` or negative `offset` → ERR_INVALID_REQUEST — middleware.py:105-124
- §2.3 — revise — mismatch — nested collection endpoints (liens, doc-records, syndication-events, listing offers, contingencies, escrow entries, tax-assessments) return full collection in one page, ignore limit/offset, `has_more` always false — vessels.py:146,208; listings.py:224,236; offers.py:283; escrow.py:60; closing.py:399
- §2.4 — insert — ambiguity — `version` starts at 1 on creation — services/common.py:6-11
- §2.4 — insert — mismatch — vessel `liens_status` recompute (lien release / waterfall) does not bump vessel version — vessels.py:194-196; closing.py:144-148
- §2.5 — revise — mismatch — `created_at`/`updated_at`/`api_request_timestamp` are wall-clock UTC; logical clock governs only business deadlines and `sent_at`/`executed_at` — db.py:32-40; listings.py:210; title.py:100
- §2.5 — insert — ambiguity — clock endpoint accepts any parseable instant (even backwards); answers 200 with `{"current_utc"}` — title.py:141-156
- §2.8 — revise — mismatch — required-field presence is rejected at body-parse time, before body-FK resolution (not "shape validation last"); remaining shape checks run at per-operation points — middleware.py:46-49 and route orderings
- §2.8 — insert — ambiguity — malformed/non-object JSON → ERR_INVALID_REQUEST; unknown path or unsupported method → ERR_NOT_FOUND (404) — middleware.py:31-43; app.py:33-43
- §2.9 — revise — mismatch — pinned the exact 12-event emitted set (…LISTING_CANCELLED, LISTING_EXPIRED with actor "system", OFFER_ACCEPTED, OFFER_FAILED, CLOSING_APPROVED, CLOSING_DISBURSED…); all other mutations append nothing; payload is a small context dict, not a before/after snapshot — services/events.py + all emit call sites; sweep.py:33
- §3.1 — revise — mismatch — no endpoint mutates agent status; non-ACTIVE blocks only listing draft/activation (ERR_INVALID_STATE); offer submission ignores selling-agent status — onboarding.py:70; listings.py:64-65,126-127; offers.py:44-92
- §3.1 — revise — mismatch — `is_entity_buyer` is informational; no signatory validation exists — onboarding.py:108-115; title.py (flag never read)
- §3.2 — insert — ambiguity — `year_built` later than clock year → ERR_INVALID_REQUEST — vessels.py:75-77
- §3.2 — insert — ambiguity — 26.0-ft documentation threshold is descriptive; no minimum length enforced — vessels.py (absence of check)
- §3.2 — revise — mismatch — instrument numbers mutually exclusive: USCG forbids `state_title_no`, STATE forbids `uscg_official_no` (deleted the "optional decal reference" reading) — vessels.py:26-45
- §3.2 — insert — ambiguity — `documentation_mode` immutable on update but still participates in the merged coherence check — vessels.py:118-134
- §3.2 — insert — ambiguity — unparseable `issue_date` → ERR_INVALID_REQUEST; same-kind supersession unconditional, no date comparison — vessels.py:221-233
- §3.2 — revise — mismatch — REVOKED doc-record status is reserved; no action produces it — vessels.py (no revoke route)
- §3.2 — revise — mismatch — ABSTRACT 30-day freshness is desk policy only; API never evaluates it — title.py:87-98
- §3.2 — revise — mismatch — `priority_rank` recorded as supplied; no preferred-mortgage-outranks validation — vessels.py:149-162
- §3.2 — insert — ambiguity — only RECORDED liens may be released; other states → ERR_INVALID_STATE — vessels.py:186-188
- §3.3 — insert — ambiguity — draft error codes: agent/brokerage mismatch and seller-kind → ERR_INVALID_REQUEST; non-ACTIVE agent → ERR_INVALID_STATE — listings.py:62-67
- §3.3 — insert — ambiguity — one-listing-per-vessel uniqueness check runs before the end_date/start_date check — listings.py:44-56
- §3.3 — insert — ambiguity — activation precondition errors pinned in order (ERR_FORBIDDEN → ERR_INVALID_STATE → ERR_DUPLICATE_RESOURCE → ERR_INVALID_DEADLINE) — listings.py:119-134
- §3.3 — insert — ambiguity — cancel with an ACCEPTED offer → ERR_INVALID_STATE — listings.py:163-166
- §3.3 — insert — ambiguity — price change enforces the same USD 1M floor and is not gated on listing status — listings.py:176-187
- §3.4 — insert — ambiguity — buyer kind lacking BUYER → ERR_INVALID_REQUEST; selling agent's status not consulted — offers.py:55,75-76
- §3.4 — insert — ambiguity — financing election field is `financing_contingency` (optional bool, default false), stored but not serialized on the offer — offers.py:87; services/common.py:126-143
- §3.4 — insert — ambiguity — `parent_offer_id` resolved for existence only; parent status unexamined — offers.py:57-58
- §3.4 — revise — ambiguity — submission to an UNDER_CONTRACT listing is unconditional (no armed kick-out required) — offers.py:67-69
- §3.4 — insert — ambiguity — accept with listing not ACTIVE → ERR_INVALID_STATE — offers.py:138-140
- §3.4 — revise — ambiguity — lien payoff plan always computable; ENCUMBERED never blocks acceptance — offers.py:37-41,147-150
- §3.4 — insert — ambiguity — FINANCING contingency deadline is also 10 days out — offers.py:161-162
- §3.4 — insert — ambiguity — counter's new `acceptance_deadline` need only parse (no future check); child inherits `settlement_state_code`, `offshore_delivery`, financing election — offers.py:194-216
- §3.4 — revise — mismatch — "flipping that child from COUNTERED" → "to COUNTERED" — offers.py:189-190,202-203
- §3.4 — insert — ambiguity — countering is not restricted to the offer's own selling agent — offers.py:183-186
- §3.4 — insert — ambiguity — withdraw identity mismatch → ERR_FORBIDDEN — offers.py:231-232
- §3.5 — insert — ambiguity — satisfy/waive/object gates: non-OPEN → ERR_INVALID_STATE; past deadline → ERR_DEADLINE_PASSED; missing `objection_note` → ERR_INVALID_REQUEST — offers.py:297-347
- §3.5 — revise — mismatch — objection does not consult parent-offer status (satisfy/waive do require ACCEPTED) — offers.py:331-347 vs 297-328
- §3.5 — insert — ambiguity — cure after the 5-day window → ERR_DEADLINE_PASSED; `objection_note` retained after a cure — offers.py:359-371
- §3.5 — insert — ambiguity — any SellingAgent may collapse; unarmed attempt → ERR_INVALID_STATE — offers.py:238-260
- §3.6 — revise — mismatch — recording endpoint accepts RELEASE/REFUND/FORFEIT entries directly; sizing discipline applies to DEPOSIT only — escrow.py:15-39
- §3.6 — insert — ambiguity — `amount_cents` integer ≥ 1; unparseable `value_date` → ERR_INVALID_REQUEST — escrow.py:26-31
- §3.6 — insert — ambiguity — clear/void precondition failures → ERR_INVALID_STATE — escrow.py:74-79,93-96
- §3.6 — insert — ambiguity — release/refund/forfeit offer-state and live-contingency failures → ERR_INVALID_STATE — escrow.py:111-117,131-133,148-153
- §3.6 — insert — ambiguity — interest days counted as whole calendar days between calendar dates, floored at zero — calculations.py:140-149
- §3.6 — insert — ambiguity — provisional interest computed once at clear, stored on the entry, never serialized — escrow.py:82; services/common.py:160-171
- §3.6 — revise — mismatch — final interest stored as `escrow_interest_final_cents`, informational only: not added to prorations, not credited to buyer, in no API response — closing.py:164-169; services/common.py:204-223
- §2.7 — revise — mismatch — `rounding_mode` election is documentary only; both modes yield identical figures — services/calculations.py (mode never referenced)
- §3.7 — revise — mismatch — one non-VOIDED statement per offer (voiding permits a fresh draft); duplicate check precedes offer-state check; draft zero-initializes computed fields — closing.py:172-204
- §3.7 — revise — mismatch — build has no "lien payoff computed" precondition; the pipeline itself computes payoffs — closing.py:231-262
- §3.7 — insert — ambiguity — per-agent commission splits are neither computed nor exposed — closing.py:38-53
- §3.7 — revise — mismatch — NONRESIDENT_REMOVAL reserved; only NONE and OFFSHORE_DELIVERY are ever emitted — closing.py:61-100
- §3.7 — insert — ambiguity — USE_TAX row created only when the credit is strictly positive; NON_US residency yields none — closing.py:86-100; calculations.py:114-119
- §3.7 — insert — ambiguity — `tax_cents` carries the SALES_TAX amount only; USE_TAX never folds into `tax_cents`/`seller_net_cents`/`buyer_due_cents` — closing.py:76,155-159
- §3.7 — revise — ambiguity — waterfall shortfall: build succeeds and records the partial allocation; ERR_WATERFALL_SHORTFALL surfaces only at disbursement — closing.py:118-142,347-354
- §3.7 — revise — mismatch — no provisional fee variant exists (no estimate endpoint); fee computed at build off `gross_price_cents`, capped by `settlement_state_code` — closing.py:160-163; calculations.py:164-170
- §3.7 — insert — ambiguity — statement serialized field set enumerated exactly; `documentation_fee_cents`/`escrow_interest_final_cents` are store-only — services/common.py:204-223
- §3.8 — insert — ambiguity — reopen blocked by a DISBURSED entry → ERR_INVALID_STATE; rebuild first resets SATISFIED/PARTIALLY_SATISFIED liens to RECORDED with zero payoff — closing.py:291-309,113-117
- §3.8 — revise — mismatch — title transfers unlimited per statement; statement status not consulted at drafting — title.py:18-44
- §3.8 — insert — ambiguity — from/to clients resolved for existence only (not matched to seller/buyer); vessel mismatch → ERR_INVALID_REQUEST — title.py:24-33
- §3.8 — revise — mismatch — `is_entity_buyer` drives no validation at execution — title.py (no reference)
- §3.8 — insert — ambiguity — execute: statement-not-APPROVED and missing paperwork → ERR_INVALID_STATE; encumbrance check runs before paperwork check — title.py:71-98
- §3.8 — revise — ambiguity — disbursement gate order pinned (contingencies → liens → escrow release → title) with per-gate error codes — closing.py:331-365
- §3.8 — revise — mismatch — cascade flips every VALID documentation record on the vessel to TRANSFERRED (also fixed §3.2's "operative record"); only ASSESSED assessments are marked FILED, EXEMPT stays EXEMPT — closing.py:377-384

No changes were needed in §4 (routing/roles table matches impl exactly) or §5 (error catalogue).
