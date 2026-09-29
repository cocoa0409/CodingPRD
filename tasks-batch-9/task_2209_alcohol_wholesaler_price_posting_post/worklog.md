# Worklog — task_2209_alcohol_wholesaler_price_posting_post

## Step 1: Create task directory — 2026-09-01T00:00:00.000Z

Created `tasks/task_2209_alcohol_wholesaler_price_posting_post/` and `tasks/task_2209_alcohol_wholesaler_price_posting_post/workspace/` (directory name pre-allocated by the caller; no index scan performed).

## Step 2 (resume, part a): Generate SCAFFOLD_CORNER_DESIGN.yaml — 2026-09-01T04:05:00.000Z

RESUME CONTEXT: the original Step 2 run crashed after writing `SCAFFOLD.yaml` (2711 lines, valid, 13 top-level keys, no design keys) and `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (787 lines, valid YAML), but before writing `SCAFFOLD_CORNER_DESIGN.yaml`. Subagent summary verbatim:

Step 2 tail is complete. `SCAFFOLD_CORNER_DESIGN.yaml` is written, complete, and lint-clean.

**Deliverable:** `SCAFFOLD_CORNER_DESIGN.yaml` (7386 lines, single top-level key `scaffold_corner_design:`)

**Instance count by `section:`** (all nine claim-extraction-guide sections present, 107 instances total):

| section | instances | of which `excluded_because:` stubs |
|---|---|---|
| entities | 13 | 0 |
| state_machines | 25 | 2 |
| calculations | 19 | 4 |
| validations | 29 | 0 |
| endpoints | 6 | 0 |
| errors | 2 | 0 |
| rbac | 7 | 0 |
| cross-cutting complexity layers | 4 | 1 |
| consistency model | 2 | 0 |
| **total** | **107** | **7** |

**Stubs vs full recipes:** 100 instances carry a fully executable `test_recipe` (`setup` + `setup_api_calls` + `trigger` + `assert`); 7 are `excluded_because:` stubs with no `test_recipe`. The 7 stubs map one-to-one onto the 7 §1.8 depth instances (`dual_variant_calc` ×2, `combinatorial_formula` ×3, `non_linear_state_machine` ×2), each cited in the SKILL's `rule_id / instance_name` form, so no corner is stubbed that §1.8 does not actually cover.

**Coverage highlights:** all 47 error ids in §1.6 are triggered at least once (two grouped 404-sweep instances cover the 12 NOT_FOUND codes; the rest fall out of the validations/state_machines/rbac instances); all 22 validation priorities including an 8-rung priority-ladder chain (auth → authz → path → body shape → body FK → wholesaler scope → OCC → state); both §1.2.1 concurrency rules as OCC stale-version tests using their declared `write_endpoint`/`occ_field`; all 16 calculations with pre-computed literal expectations at their boundaries (deadline millisecond, half-open hold/correction windows, clerical limit exactly at 0.10, round_half_up half-cent, surcharge and combination band edges, cooldown buffer end); terminal-state lockdown for WITHDRAWN / REJECTED / DENIED / CLOSED; the `ops_run_checkpoint` layer via a no-op second posting run.

**§1.5 gaps:** none. Every one of the 100 chains is reachable from an empty database by composing existing §1.5 endpoints (ladder rung 1 only) — **no endpoint was added and `SCAFFOLD.yaml` was not modified in any way**, nor was `SCAFFOLD_DIFFICULTY_DESIGN.yaml`. Two preconditions were restructured rather than requiring new surface: (a) "no posted price exists" is observed through `off_posted_detection`/`UNPOSTED_BRAND` because §1.6 declares no error for it on `GET …/posted-price`; (b) the FLAGGED→VALIDATED revalidation cycle is driven by `hold-amendments/{id}/revoke` rather than an error correction, since the correction window closes before any posting run can make prices effective.

**Validation results:**
- `python3 -c "import yaml; … assert list(d.keys())==['scaffold_corner_design']"` → passes; 9 sections, 107 instances.
- `scaffold_lint.py tasks/task_2209_...` → `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (1632 calls scanned across §1.8 + §1.9; 62 endpoints, 14 entities).
- Both mandatory replay checks were run over every instance: `${var}` closure is complete (no placeholder is read before it is captured, including in `assert:` lines), every recipe opens by setting the logical clock, and no `assert:` expected value contains a placeholder or non-literal. `name` is unique across §1.8 ∪ §1.9 (verified programmatically, zero collisions), and every `claim_type:` is drawn from its section's row set in `references/claim-extraction-guide.md`.

**One pre-existing condition to note for the worklog (not introduced here):** `SCAFFOLD_DIFFICULTY_DESIGN.yaml` contains only 7 instances across 3 rule_ids, below the SKILL's §1.8 minimum of ~18 across 9 rules. Per the assignment's instruction that both existing files are frozen, it was left unmodified.

ORCHESTRATOR NOTE: the flagged §1.8 shortfall was independently verified (`rule_id`s present: dual_variant_calc/2, combinatorial_formula/3, non_linear_state_machine/2 — rules 4–9 absent entirely). This confirms the crash truncated §1.8 mid-generation. Per RESUME MODE's "treat a truncated artifact as missing", Step 2 part b repairs it.

## Step 2 (resume, part b): Repair truncated SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8 rules 4-9) + re-dedup §1.9 — 2026-09-01T04:35:00.000Z

Subagent summary verbatim:

Step 2 artifact repair is complete. Both files are written, parse cleanly, and the lint is clean.

## PART 1 — §1.8 now at full strength

`SCAFFOLD_DIFFICULTY_DESIGN.yaml` grew 787 -> 2074 lines. Six blocks appended in §0.5 order; the 3 pre-existing blocks were not touched (first 787 lines byte-identical to the pre-edit file).

| # | rule_id | instances |
|---|---|---|
| 1 | dual_variant_calc | 2 (pre-existing) |
| 2 | combinatorial_formula | 3 (pre-existing) |
| 3 | non_linear_state_machine | 2 (pre-existing) |
| 4 | transitive_cascade | 2 (new) |
| 5 | priority_pair_validation_conflict | 2 (new) |
| 6 | boundary_precision_check | 2 (new) |
| 7 | cross_entity_state_dependency | 2 (new) |
| 8 | resource_temporal_overlap | 2 (new) |
| 9 | compensating_invariant | 2 (new) |
| | **total** | **19** |

The 12 new instances and the §0.5 differentiation each claims:

1. `posting_run_supersession_cascades_from_new_item_through_tier_to_prior_schedule` — trigger `POST /posting-runs`; depth-4 single-file chain (new item EFFECTIVE -> prior item SUPERSEDED + `supersedes_item_id` -> that item's tier INACTIVE at a frozen 108000 -> prior schedule SUPERSEDED with `superseded_by_schedule_id`).
2. `second_approved_correction_cascades_from_schedule_counter_into_the_wholesaler_penalty_ledger` — different trigger (`POST /error-corrections/{id}/approve`); depth-3 chain where the identical earlier approval left the wholesaler at 0, proving link 2 is caused by `PriceSchedule.correction_count` reaching 2, not by the approval.
3. `suspended_license_business_safety_outranks_the_unregistered_brand_prerequisite_on_submit` — error-category pair business_safety (p9 `ERR_LICENSE_NOT_ACTIVE`) vs business_prerequisite (p10 `ERR_BRAND_NOT_REGISTERED`) on submit; clearing only the licence flips the answer to the p10 error.
4. `already_approved_correction_state_outranks_the_exhausted_schedule_correction_quota` — a *different* pair: state (p8 `ERR_INVALID_STATE`) vs business_quota (p18 `ERR_CORRECTION_LIMIT_EXCEEDED`), both live on the same exhausted schedule.
5. `audit_tier_multiplier_holds_at_exactly_two_prior_violations_and_escalates_at_three` — numeric threshold metric (`off_posted_violation_count` vs `TIER_1_MAX_PRIOR`) on `POST /compliance-audits/{id}/assess`: prior 2 -> 1.00 -> 4000 (not 6000); prior 3 -> 1.50 -> 12000.
6. `zero_case_line_collapses_the_depletion_cap_to_zero_and_empties_the_eligible_tier_set` — the empty-collection/zero-count edge, on a *different* endpoint (`POST /retailer-invoices/{id}/validate`) and metric: `cases_quantity` 0 makes the depletion cap 0 and the eligible tier set empty, so 1 cent of allowance flags a line whose charged prices match the posted prices exactly.
7. `retailer_invoice_revalidation_is_gated_by_the_collecting_compliance_audit_state` — entity pair (RetailerInvoice, ComplianceAudit): one invoice gate mapped across three audit states (COLLECTED refuse, ASSESSED refuse, VOID admit) with no edit to the invoice.
8. `error_correction_filing_is_gated_by_the_price_schedule_item_status_across_draft_posted_effective` — different pair (ErrorCorrection, PriceScheduleItem) and a three-valued gate: refused at DRAFT, admitted at POSTED and again at EFFECTIVE with an identical body.
9. `brand_registration_closed_intervals_collide_on_a_single_shared_endpoint_instant` — Brand resource with CLOSED-interval semantics: a start equal to the incumbent's `registration_expires_on` is refused, one millisecond later is admitted.
10. `combination_window_cooldown_conflicts_backward_through_the_buffered_requested_end` — CombinationSale resource with the opposite semantics (HALF-OPEN, symmetric 7-day buffer, strict `<`), and it probes the *second* conflict clause: requested end 2026-10-25T00:00:00.001Z buffers past the incumbent's start by 1 ms and is refused; ...00.000Z buffers to exactly that start and is admitted.
11. `withdraw_conserves_the_wholesaler_late_filing_penalty_ledger_to_the_cent` — conserved quantity = the money ledger, pinned as `penalty_exposure_cents == late + correction + amendment + assessed` (0 -> 250000 -> 0), with `is_late`/`filed_at` retained and `version` advanced to 3, not rewound.
12. `revoke_conserves_the_item_price_vector_and_every_derived_instrument_value` — a *different* conserved quantity: the price vector and derived instruments, pinned as three formulas; (108000, 150000, 135000, ACTIVE) -> (106200, 148000, 140600, VOID) -> restored.

Every recipe sets the logical clock first, builds from an empty database using only §1.5 endpoints, threads `${var}` for server-minted ids/versions, and locks asserts to pre-computed literals. Both replay checks were applied during authoring; numbers and fixtures were deliberately chosen to avoid re-using any value the 7 existing instances already claim.

## PART 2 — §1.9 re-deduplication (conservative)

3 genuine duplicates converted to `excluded_because:` stubs (`test_recipe` deleted, `name`/`claim_type`/`grounds`/`distinguishing_aspect` kept): `posting_run_supersedes_items_then_bubbles_the_supersession_up_to_the_prior_schedule`, `price_schedule_withdraw_compensates_the_late_filing_penalty_it_had_accrued`, `hold_amendment_revoke_restores_prior_prices_and_reactivates_the_voided_combination_sale` — each citing the covering §1.8 instance in `rule_id / instance_name` form.

Deliberately kept with `test_recipe` intact (different angle, would have been a coverage gap): `posting_run_deactivates_only_the_tiers_of_items_it_superseded`, `combination_cooldown_admits_a_window_starting_exactly_at_the_buffer_end`, `brand_registration_intervals_overlap_only_within_the_same_brand_name_and_beverage_class`, `approving_an_error_correction_cascades_through_the_item_the_tier_and_both_correction_counters`, the four plain single-rule versions of the priority pairs, `compliance_audit_void_compensates_the_whole_assessment_across_wholesaler_and_invoices`, `compliance_audit_collect_pulls_flagged_invoices_under_audit_and_records_one_finding_per_line`, `quantity_discount_ignores_tiers_whose_min_cases_exceeds_the_line_quantity`, `an_invoice_line_with_no_cases_and_no_bottles_returns_zero_quantity_line`, `off_posted_detection_treats_an_item_with_no_posted_price_as_a_whole_gross_finding`, `hold_amendment_rejections_accrue_the_frivolous_penalty_only_on_reaching_three`.

## Validation results

- §1.8 parse: 9 rule_ids, >=2 each, total 19. PASS
- §1.9 parse: single top-level key, 9 sections, 107 instances, now 10 stubs / 97 full recipes (was 7 / 100); zero instances with both `test_recipe` and `excluded_because`, zero with neither. PASS
- Name uniqueness across §1.8 U §1.9: 126 names, 0 collisions. All 10 `excluded_because` citations resolve to a real §1.8 rule_id/instance. PASS
- `scaffold_lint.py`: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5` (62 endpoints, 14 entities, 19 §1.8 instances, 97 §1.9 instances, 1796 calls). PASS
- `SCAFFOLD.yaml` md5 `5b11194a375874ae228517c038b23609` at start and at end — byte-identical. PASS
- Pre-existing §1.8 content: diff of the first 787 lines against the pre-edit copy is empty. PASS
- `workspace/INSTRUCTION.md` and `worklog.md` untouched; no new files left in the task directory.

## Step 3: Copy shared files — 2026-09-01T04:36:00.000Z

Already satisfied by the crashed run: `workspace/INSTRUCTION.md` verified byte-identical to project-root `INSTRUCTION.md` (`diff` empty). No action taken.

## Step 4: Generate PRD — 2026-09-01T05:30:00.000Z

Subagent summary verbatim:

PRD written to `workspace/PRD.md`.

## Size
- **459 lines**, **94,085 characters**. Ends at §5 with the final error row; no audit footer, no placeholders, no truncation.

## Section outline
- `# Alcohol Price Posting API — Product Requirements Document`
- **§1 Introduction** — 3 paragraphs (post-and-hold statutory context, what the system of record covers and why boundary precision is legally load-bearing, the two audiences plus the logical clock rationale).
- **§2 Global Specifications & System-Wide Principles** — 12 subsections: 2.1 User and Role-Based Access Control / 2.2 API Response Structure (pasted byte-for-byte from `section-2.2-response-structure.md`) / 2.3 Pagination, Ordering and Filtering of Collections / 2.4 The Logical Posting Clock / 2.5 Record Identity, Revision Counters and the Audit Trail / 2.6 Money, Percentages and Rounding / 2.7 Window Arithmetic and Boundary Inclusivity / 2.8 Cascade Discipline Across Schedules, Items, Tiers and Combinations / 2.9 The Four Penalty Buckets and Total Exposure / 2.10 The Order of Rejection (all 22 priorities as an ordered list) / 2.11 Path Resolution and Wholesaler Ownership / 2.12 Optimistic Concurrency Control.
- **§3 Business Logic & Workflows** — 9 subsections: 3.1 Standing Up a Program, its Licensees and its Filing Staff / 3.2 Brand Registration as a Posting Prerequisite / 3.3 Assembling and Filing the Monthly Price Schedule / 3.4 Certification, the Post-and-Hold Window and Segregation of Duties / 3.5 Quantity Discount Tiers and Combination Sales / 3.6 Competitive Amendments and Clerical Corrections / 3.7 Taking Prices Effective: The Posting Run and Posted-Price Resolution / 3.8 Retailer Invoicing and Off-Posted-Price Detection / 3.9 Compliance Audits, Penalty Assessment and Exposure Reporting.
- **§4 Endpoint Definitions** — status-code intro paragraph + 4-column table, 62 rows.
- **§5 Error Code Catalogue** — 2-column table, 47 rows.

## Contract reports

Field coverage check: entities[].fields 150/150; endpoints[].input 152/152; endpoints[].output structured field names 17/17. Status: PASS (two independent passes, identical results.)

Rule coverage check: 22/22 validations with priority expressed in prose (§2.10, ordered 1-22); 2/2 concurrency_rules OCC rejections; 21/21 state_machines transitions; 15/15 calculations (incl. both variants of the 2 dual-variant rules = 17 variant-level rules); 19/19 calculation constants stated numerically; 47/47 error conditions matchable to error_id in prose; 308/308 side_effects/applies_to entries; 150 fields + 36 enum members reconstructible from prose; sibling-branch symmetry 7 groups checked, 0 asymmetric. Status: PASS

Path purity check (§3 only): 785 backtick tokens scanned, 0 starting with `/`, 0 bare HTTP-method tokens, 0 method+path tokens. Status: PASS

No-pseudocode scan: 0 occurrences of comparison/arithmetic/function-call operators outside the §2.2 JSON fences; 0 fuzzy quantifiers.

## Self-audit vs. scaffold
- **14 / 14 entities** narrated with every field, type, default, initial value and constraint — including `AuditFinding`'s `common_fields: false` treatment (only `id` and `created_at`; no `updated_at`, no `version`, stated explicitly in §2.5).
- **62 / 62 endpoints** in the §4 table with exact method, path, description and role list; all 16 read collections' filter sets enumerated in §2.3.
- **47 / 47 error IDs** in §5 with statuses matching the scaffold exactly, and every one also appears with its triggering condition in §1-§3 prose (verified programmatically).
- **22 / 22 validation priorities** in strict ascending order in §2.10, each with error ID, HTTP status and full `applies_to` endpoint set, plus three worked precedence consequences.
- **21 transitions across 5 state machines** (PriceSchedule 6, HoldAmendment 3, ErrorCorrection 2, RetailerInvoice 6, ComplianceAudit 4), each with preconditions, error IDs, and both branches of every conditional side effect.
- **3 / 3 roles** with `identity` translated: `FilingAgent` and `CertifyingOfficer` as `entity_backed:LicenseeUser` (with `DUAL_ROLE` and `is_active` semantics), `ComplianceOfficer` as opaque with no `X-User-ID` resolution and no ownership narrowing.
- **2 / 2 concurrency rules** in §2.12, framed purely in stale-version terms.

**One discrepancy with the task brief:** the brief said 16 calculations; `SCAFFOLD.yaml` contains exactly **15** named `calculations[]` entries. Two of them (`posted_case_price_resolution`, `wholesaler_penalty_exposure`) are dual-variant, giving 17 variant-level rules — likely the source of the "16". All 15 are covered, both variants each.

**Determinism gaps in the scaffold that the PRD had to close** (flagged so the test author knows these are PRD-originated, not scaffold-originated): the default for the posted-price capability's `as_of` (current logical clock instant); the null response shape when no posted price resolves; the single-`finding_type` selection precedence for a line that is simultaneously unposted / off-posted / over-allowance; posting-run processing order and the ordering of `effective_schedule_ids` / `superseded_schedule_ids`; and the general "one `version` increment per record per mutating request" rule that reconciles the scaffold's per-transition version callouts.

ORCHESTRATOR VERIFICATION: 459 lines / 94085 chars confirmed; 5 top-level sections present; file ends on a complete error-catalogue table row (non-truncated).

## Step 6: Generate Implementation — 2026-09-01T06:05:00.000Z

Subagent summary verbatim:

The implementation is complete and verified.

## File inventory
Root: `workspace/implementation/`

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | reads `$PORT`, installs deps quietly, `exec python3 app.py` in foreground |
| `requirements.txt` | 1 | `flask>=2.0` |
| `app.py` | 83 | `create_app()`, blueprint registration, per-request lock, error handlers, `0.0.0.0:$PORT` |
| `store.py` | 216 | in-memory `db` (14 dicts), logical clock, insertion sequence, `new_record`/`bump`/`bump_if_changed` |
| `errors.py` | 124 | `ApiError`, all 47 error ids + statuses + default messages |
| `envelope.py` | 59 | object/list/error envelopes, `req_` + 20 uppercase alnum ids |
| `auth.py` | 81 | header auth, role resolution, `require_scope` (13 write endpoints) |
| `validators.py` | 269 | body/field coercion, FK `must_find`, pagination, filters, enum/instant query params |
| `calc.py` | 431 | all 15 calculations (Decimal + ROUND_HALF_UP) |
| `services.py` | 152 | exposure/tier/combo/invoice recomputation cascades |
| `serialize.py` | 15 | response projection |
| `routes/__init__.py` | 21 | blueprint list |
| `routes/clock.py` | 19 | `POST /_clock/set_current_utc` |
| `routes/programs.py` | 235 | state programs, wholesalers, licensee users, penalty exposure |
| `routes/brands.py` | 117 | brands + approve/reject |
| `routes/schedules.py` | 478 | schedules, items, posted-price, posting runs |
| `routes/instruments.py` | 175 | quantity discount tiers, combination sales |
| `routes/adjustments.py` | 310 | hold amendments, error corrections |
| `routes/invoices.py` | 181 | retailer invoices, invoice lines, validation |
| `routes/audits.py` | 272 | compliance audits, findings, assessment |

Total 3,249 lines. No stubs, no elisions.

## Endpoint coverage
Programmatic diff of `app.url_map` against the PRD §4 table: **62 implemented, 62 in PRD, zero missing, zero extra**. (`static_folder=None` keeps Flask from adding a 63rd rule.) Error catalogue diff: 47 PRD ids vs 47 in `errors.py` — no missing, no extra, no status mismatches.

## Boot smoke test
`PORT=18399 bash start.sh` booted clean from a fresh process. Fresh-boot state is empty (`total_count: 0` for all collections, clock back at `2026-08-01T00:00:00.000Z`), `POST /state-programs` returned 201 with a well-formed envelope and all documented defaults, an unauthenticated GET returned 401 `ERR_UNAUTHENTICATED`, and an unrouted path returned a well-formed `ERR_NOT_FOUND` error envelope. Server killed afterward; no listeners remain.

Two end-to-end scripted runs passed with no failures:
- Run 1 (69 assertions): effective date, hold window, tier 105000 -> 110250 after correction, combo floor 180000/min 162000, cooldown conflict, both OCC 412s, amendment accept + revoke round-trip, posting run over 2 schedules, `as_amended` 126000 vs `as_certified` 120000, full invoice line math (gross 720000, discount 94500, allowed promo 36000 / excess 14000, allowed depletion 900 / excess 100, net 588600, posted gross 756000, variance 36000, finding variance 50100), invoice rollups (subtotal 588600, surcharge 2943, total 591543, FLAGGED), finding `OFF_POSTED_UNDERCHARGE` penalty component 20040, audit void reversing to zero.
- Run 2 (26 assertions): late filing accrual 250000 and its exact reversal on withdraw, deadline instant `T23:59:59.999Z` treated as on time, return-for-correction, correction quota 409, correction window 409 at day 15, third frivolous rejection accruing 75000 exactly once, self-reference 409, hold window 409 at exactly `hold_window_ends_at`, `provisional_exposure` variant, UNDER_AUDIT freeze on both validate and line-add, void-from-CLOSED 409, suspended-licence 409, clean re-validation to VALIDATED with zeroed rollups, `ERR_NO_FLAGGED_INVOICES` 409.

Storage is process memory only: no SQLite, no file writes, no `/tmp` cache. No data is seeded at startup.

## PRD ambiguities and chosen interpretations
1. **Auth header names.** PRD §2.1 says `X-User-Role` / `X-User-ID`; SCAFFOLD.yaml mentions `X-Role`. Chose the PRD names.
2. **`state_code` / `license_number` uniqueness.** Implied natural keys, but the catalogue has no error id for them, so no uniqueness is enforced.
3. **Duplicate ids in `member_item_ids`.** Distinctness only gates `ERR_COMBINATION_TOO_FEW_MEMBERS`; duplicates still contribute to the floor sum, applied identically at create time and in the post-amendment cascade.
4. **Repeat-correction penalty threshold.** "reaches 2" read as exactly 2 (fires once), while the frivolous-amendment rule's "3 or more" is read as `>= 3` with the penalty accrued only on the transition.
5. **Schedule version on correction approval.** §2.5 says every record changed in a request bumps once, so approving a correction bumps the item and its owning schedule (whose `correction_count` changes) as well as the correction.
6. **`variance_pct`.** Computed as a `Decimal` internally, emitted as a JSON float.
7. **Out-of-catalogue failures.** Unrouted paths -> `ERR_NOT_FOUND` (404), wrong method -> `ERR_METHOD_NOT_ALLOWED` (405), unexpected exception -> `ERR_INTERNAL` (500), all in the standard error envelope.
8. **Tie-breaks.** Posting-run ordering and posted-price resolution add `created_at` then insertion sequence after the PRD's stated keys, so ordering is total and deterministic.
9. **Late-penalty reversal amount.** Withdrawal reverses using the program's current `late_filing_penalty_cents` (verified to return the wholesaler to exactly zero).
10. **Audit `prior_violation_count`.** Captured before the current audit's findings are added to the wholesaler's lifetime count, so the tier multiplier reflects prior history only.

## Step 5: Generate Unit Tests — 2026-09-01T06:35:00.000Z

Subagent summary verbatim:

All queues are complete and programmatic verification passes.

## Tests emitted — 143 total

**Queue A (Difficulty, §1.8) — 47 tests, 9 files, 19/19 instances covered**

| file | tests |
|---|---|
| `test_01_dual_variant_reads.py` | 5 |
| `test_02_invoice_line_pricing_composition.py` | 5 |
| `test_03_audit_penalty_rounding_and_escalation.py` | 5 |
| `test_04_promotional_and_registration_intervals.py` | 6 |
| `test_05_filing_lateness_and_withdrawal.py` | 5 |
| `test_06_hold_amendment_branches.py` | 5 |
| `test_07_posting_run_supersession_and_correction_gate.py` | 6 |
| `test_08_correction_approval_cascade_and_quota.py` | 5 |
| `test_09_submission_prerequisites_and_audit_custody.py` | 5 |

**Queue B (Corner, §1.9) — 96 tests, 13 files, 96/97 non-stub instances covered**

| file | tests | sections |
|---|---|---|
| `test_11_entity_shapes_and_identity.py` | 12 | entities |
| `test_12_roles_and_error_catalogue.py` | 9 | rbac, errors |
| `test_13_price_schedule_lifecycle.py` | 7 | state_machines |
| `test_14_amendment_and_correction_lifecycle.py` | 7 | state_machines |
| `test_15_invoice_and_audit_lifecycle.py` | 6 | state_machines |
| `test_16_posting_window_calculations.py` | 11 | calculations |
| `test_17_invoice_and_penalty_calculations.py` | 4 | calculations |
| `test_18_collection_reads_and_posting_runs.py` | 6 | endpoints |
| `test_19_concurrency_and_read_consistency.py` | 5 | cross-cutting complexity layers, consistency model |
| `test_20_rejection_priority_order.py` | 10 | validations |
| `test_21_filing_and_registration_refusals.py` | 12 | validations |
| `test_22_pricing_instrument_refusals.py` | 7 | validations |

All 10 `excluded_because:` stubs produced zero tests (verified: no `Design:` tag resolves to a stub).

## Instances SKIPPED — 1

`Corner/entities/price_schedule_item_referencing_a_brand_of_another_wholesaler_is_forbidden` — **condition 2 failure** (PRD does not uniquely derive the asserted outcome). The instance asserts a refusal when an item names a brand owned by a different wholesaler. PRD §3.3 line 218 enumerates item creation's complete refusal set (`ERR_CASE_PRICE_EXCEEDS_UNIT_AGGREGATE`, `ERR_DUPLICATE_SCHEDULE_ITEM`, and it explicitly states "Item creation imposes no state requirement on the parent schedule"), and §2.11 scopes `ERR_FORBIDDEN_WHOLESALER_SCOPE` on `POST /price-schedule-items` to *the wholesaler of the target schedule versus the acting agent*, never to the brand's owner. The cross-wholesaler brand case is a **closed-enumeration silence**: the PRD says which refusals exist and this is not among them, so neither a refusal code nor a success is derivable. Gap left as a gap. Queue A had zero skips.

## `test_helpers/` inventory (9 files)

`__init__.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py` — plus `test_suite/conftest.py`.

## Programmatic verification (AST-based)

- Design indices parsed structurally: 19 Difficulty instances / 0 stubs; 107 Corner instances / 10 stubs -> 97 non-stub. No duplicate instance names.
- **143/143 test functions carry exactly one `Design:` line, as the final docstring line, resolving byte-for-byte to a real non-stub instance in the correct yaml.** Zero untagged, zero dual-tagged, zero unresolved, zero stub-tagged.
- Coverage: Difficulty 19/19; Corner 96/97 (the single documented skip).
- **248 `PRD §x.y: "…"` citations checked verbatim** (whitespace-normalised substring of `workspace/PRD.md`) — all pass.
- Hygiene: no `pytest.mark.skip`/`skipif`/`xfail`/`pytest.skip`; no occurrence of "scaffold" in any generated file; no `TODO`/`FIXME`/placeholder bodies.
- `python3 -m pytest test_suite --collect-only -q` -> **143 tests collected**, so every module and every helper import resolves.

Design-index defects were resolved in the PRD's favour: item `status` asserted `DRAFT` not `SUBMITTED` per §3.3; `ERR_SEGREGATION_OF_DUTIES` at 409 not 422; invoice `audit_status` `ASSESSED` not `AUDITED`; undeclared `approved_at` assertions dropped; ordering among identical `created_at` values asserted as sets since the PRD does not determine it.

## Step 7: Run Tests and Iterate — 2026-09-01T07:15:00.000Z

Subagent summary verbatim:

The task is already green. Iteration 1's 8-round parallel sweep came back fully clean, so there was nothing to diagnose or fix.

## Summary

**Iterations run:** 1

**Sweep result:** all 8 concurrent rounds passed 143/143 — `passed == total`, `failed == 0`, `errors == 0`, `skipped == 0` in every round (~191 s per round, run concurrently). Union of failing tests across rounds 1-8 is **empty**, so no flakiness signal surfaced either.

Test inventory confirmed intact and fully exercised: 143 distinct test names spread over the 21 files in `test_suite/` (5-12 tests per file), matching the expected count. No test was skipped, deselected, or errored in any round.

**Tests deleted:** none — the diagnostic protocol (STEP 0 -> STEP 3) was never entered, because STEP 0 produced an empty failure set. No test was evaluated for PRD silence or unique-derivability collapse, and none needed to be.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none.

Notes worth passing along:

- One methodological catch: my first pass at parsing the results files keyed on `t['outcome']`, which does not exist in this runner's schema — the per-test key is `t['status']`. That made every test look like a failure. The real schema is `{total, passed, failed, errors, skipped, duration_seconds, tests[{name, file, status, duration_seconds, error_message}]}`. I re-verified against `status` plus the top-level counters, which agree with each other in all 8 rounds. Worth knowing for any downstream automation reading these files.
- `/tmp/sweep1_*.log` filenames collide with another pipeline running concurrently on this host, so those logs are not trustworthy for this task. The `--results-file` paths are task-scoped and unaffected; all conclusions above come from the JSON, not the logs. A future run should use a task-specific log directory.
- `start.sh` already guards its `pip install` behind an import check, which is what keeps 8 concurrent per-test-server rounds from thrashing on boot; and `store.py` holds all state in plain in-process dicts with no disk persistence, so `start.sh` re-invocation wipes state cleanly. Both are consistent with the cardinal rules — I left them alone.
- I removed the generated `workspace/implementation/results.*.json` files afterwards so the implementation directory ships clean.

ORCHESTRATOR INDEPENDENT RE-VERIFICATION: because the Step 7 subagent deleted the `results.*.json` files that the pipeline output spec requires be retained, the orchestrator re-ran the full 8-round parallel sweep itself (task-scoped logs under `/tmp/sweep_2209/` to avoid the log-name collision noted above). Result reproduced exactly:

```
results.1.json: passed=143/143 failed=0 errors=0 skipped=0 dur=195.46
results.2.json: passed=143/143 failed=0 errors=0 skipped=0 dur=195.33
results.3.json: passed=143/143 failed=0 errors=0 skipped=0 dur=195.33
results.4.json: passed=143/143 failed=0 errors=0 skipped=0 dur=195.32
results.5.json: passed=143/143 failed=0 errors=0 skipped=0 dur=195.27
results.6.json: passed=143/143 failed=0 errors=0 skipped=0 dur=195.31
results.7.json: passed=143/143 failed=0 errors=0 skipped=0 dur=195.29
results.8.json: passed=143/143 failed=0 errors=0 skipped=0 dur=195.36
union of non-passing tests across all rounds: 0
ALL 8 ROUNDS GREEN
```

All eight `results.{1..8}.json` files are retained in `workspace/implementation/` as the output spec requires.

## Step 8: Finalize PRD — SKIPPED — 2026-09-01T07:20:00.000Z

Skip condition satisfied per the entrance skill: Step 7 exited on its first 8-round sweep with 0 test deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes and 0 `implementation/` fixes — zero iterations beyond the baseline. `PRD.md` therefore already determined every behavior the 143-test suite exercises, and there is no `<step_7_diff>` to hand off. No `PRD_FINALIZED.md` is produced; Step 9 starts from `workspace/PRD.md`.

## Step 9: Complete PRD — 2026-09-01T07:55:00.000Z

Subagent summary verbatim:

Verification complete. All 25 diff hunks reviewed individually; every hunk is a paragraph replacement whose NEW text retains the OLD text verbatim except for the six deliberate mismatch corrections. No PRD.md rule was dropped.

## Summary

**Files**
- `workspace/PRD.md` — 459 lines, 94,085 chars
- `workspace/PRD_COMPLETED.md` — 466 lines, 109,049 chars
- Delta: +7 lines, **+14,964 chars**

**Counts:** 29 ambiguity-pins, 6 mismatch-revisions (35 changes across 25 replaced paragraph hunks)

**Changes**
- §2 intro — insert — ambiguity — trailing slash on any path is not significant — `app.py:22`
- §2.1 — insert — ambiguity — header values whitespace-trimmed, blank counts as absent, role names case-sensitive — `auth.py:43-48`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alnum chars; `api_request_timestamp` read from the logical clock — `envelope.py:13-14,20`
- §2.2 — insert — ambiguity — same error envelope carries the three out-of-catalogue failures — `app.py:43-73`
- §2.3 — insert — ambiguity — empty-string query param treated as omitted — `validators.py:176-179`
- §2.3 — insert — ambiguity — insertion-sequence tie-break silently appended as final key to every stated ordering — `store.py:214-216`
- §2.3 — insert — ambiguity — filters compared as strings, bool literals `true`/`false`, empty = no restriction, unset field never matches, unrecognised params ignored — `validators.py:195-213,232-239`
- §2.4 — insert — ambiguity — `to_iso8601` required; move takes effect before the response envelope is composed — `routes/clock.py:13-19`
- §2.4 — insert — ambiguity — lenient datetime parsing (date-only, space separator, no seconds, 1-9 fractional digits, numeric offsets), UTC conversion, ms truncation, canonical output, out-of-range components rejected — `store.py:54-94`
- §2.6 — insert — ambiguity — exact decimal arithmetic over literal representations, never binary doubles — `calc.py:37-43`
- §2.7 — insert — ambiguity — correction window tests only its upper bound; no lower bound — `calc.py:116-121`
- §2.8 — **revise** — **mismatch** — combination cascade happens only on the two hold-amendment paths; correction approval touches no `CombinationSale` — `routes/adjustments.py:271`, `services.py:73-108`
- §2.9 — insert — ambiguity — withdrawal reversal reads the program's `late_filing_penalty_cents` current at withdrawal — `routes/schedules.py:230-234`
- §2.10 pri. 4 — insert — ambiguity — `YYYY-MM` month 01-12; explicit `null` = omitted; undeclared fields ignored; absent body = `{}`; non-object body is a shape violation; int fields reject bools and fractional numbers — `validators.py:87-93,104-119`
- §3.1 — **revise** — **mismatch** — `state_code` not length-checked, not case-normalised, and **no uniqueness enforced** — `routes/programs.py:81-87`
- §3.1 — **revise** — **mismatch** — `license_number` **no uniqueness enforced** — `routes/programs.py:128-148`
- §3.1 — **revise** — **mismatch** — licence-status capability follows the §2.5 conditional rule; a no-op write leaves `version`/`updated_at` untouched and still returns 200 — `routes/programs.py:158-160`
- §3.3 — insert — ambiguity — `wholesaler_id`/`state_program_id` not cross-checked; enumerates which rules read the schedule's program vs the invoicing wholesaler's vs the audit's — `routes/schedules.py:58-103`, `services.py:14-23`
- §3.5 — insert — ambiguity — tier imposes no item-status requirement; `min_cases` need not be unique — `routes/instruments.py:32-68`
- §3.5 — insert — ambiguity — `member_item_ids` stored as supplied with duplicates; distinctness only for the count test; floor sum counts each occurrence, at create and in the cascade — `routes/instruments.py:105,133,140`, `calc.py:387-391`, `services.py:54-60`
- §3.6 — insert — ambiguity — reference item's status never consulted — `routes/adjustments.py:44-74`
- §3.6 — insert — ambiguity — `variance_pct` computed once at filing, compared as exact Decimal, emitted as JSON float — `routes/adjustments.py:216-237`
- §3.6 — **revise** — **mismatch** — approval bumps three records (correction, item, owning schedule); tiers bumped only if changed; repeat-correction penalty is **equality with 2** firing exactly once, contrasted with the ">= 3" frivolous threshold — `routes/adjustments.py:260-279`
- §3.7 — insert — ambiguity — posting-run processing order gains the insertion-sequence tie-break — `routes/schedules.py:412-419`
- §3.7 — insert — ambiguity — supersession search excludes self and same-schedule items, EFFECTIVE-at-search-time only, winner by effective_date/certified_at/created_at/seq; only schedules that lost an item are rollup candidates; an item-less schedule is never superseded — `routes/schedules.py:364-388,449-464`
- §3.7 — insert — ambiguity — run response arrays ordered by `created_at`+seq, independent of processing order — `routes/schedules.py:471-476`
- §3.7 — insert — ambiguity — subject item is its own candidate; search ranges over all wholesalers; final seq tie-break — `calc.py:167-197`
- §3.8 — insert — ambiguity — line's `item_id` need not belong to the invoicing wholesaler and has no status requirement; posted price resolves under *that* item's key — `routes/invoices.py:134-136`
- §3.8 — **revise** — **mismatch** — validation gate order is `audit_status`, then line count (both `ERR_INVALID_STATE`), then licence standing — priority 8 before 9 — `routes/invoices.py:77-85`
- §3.8 — insert — ambiguity — invoice `version` bumps unconditionally; lines bump only on an actual field change; lines repriced in `created_at`+seq order — `services.py:114-140`
- §3.8 — insert — ambiguity — tier selection final seq tie-break — `calc.py:268-275`
- §3.9 — insert — ambiguity — `tier_multiplier` emitted as JSON float (1.0/1.5/2.0); `open_audit_count` is a lifetime tally never decremented — `routes/audits.py:91,99,178`
- §3.9 — insert — ambiguity — `finding_type` sequence is strict precedence (unposted and off-posted both beat over-allowance); first clause re-resolves the posted price at collection time; findings ordered with seq tie-breaks — `routes/audits.py:39-48,130-153`
- §3.9 — insert — ambiguity — "every invoice this audit collected" = every invoice whose stored `audit_id` names this audit; others passed over — `routes/audits.py:187-191`
- §3.9 — insert — ambiguity — provisional exposure rate comes from each **audit's** `state_program_id`, not the wholesaler's — `calc.py:231-232`
- §5 — insert — ambiguity — three table rows (`ERR_NOT_FOUND` 404, `ERR_METHOD_NOT_ALLOWED` 405, `ERR_INTERNAL` 500) plus a paragraph distinguishing `ERR_NOT_FOUND` from the fourteen entity-specific 404 codes — `app.py:43-73`

**Key findings beyond the supplied flagged list** (found by walking the code, not taken on trust): the §2.8 combination-cascade overreach, the §3.1 licence-status conditional bump, and the §3.8 validation gate ordering were all genuine PRD-vs-impl mismatches that were not on the list. Conversely, four listed items turned out to be already correctly pinned in PRD.md (`prior_violation_count` capture timing, the `as_of` default and null response shape, the ">= 3" frivolous threshold, and the `finding_type` clause sequence) — for those only the precedence emphasis and the re-resolution timing were added.

## Pipeline complete — 2026-09-01T08:00:00.000Z

All nine steps accounted for (Step 8 skipped by its documented skip condition). Final artifact inventory verified on disk.
