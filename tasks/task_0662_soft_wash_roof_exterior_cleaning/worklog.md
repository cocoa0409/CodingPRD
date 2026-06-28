# Worklog — task_0662_soft_wash_roof_exterior_cleaning

## Step 1: Create Task Directory — 2026-06-26T18:18:24.000Z

Directory `tasks/task_0662_soft_wash_roof_exterior_cleaning/` and `workspace/` subdir pre-existed (parallel-run directive). Skipped directory-scan / index computation; used the folder verbatim as {task_dir}. workspace/ was empty at start.

## Step 2: Generate Scaffold — 2026-06-26T18:44:38.000Z

All three scaffold artifacts for **task_0662_soft_wash_roof_exterior_cleaning** (Expert difficulty) generated and pass `scaffold_lint.py` with `VERDICT: clean lint`. All formula-derived assertions computed in code and verified (21/21 pass).

**SCAFFOLD.yaml** (§1.0–§1.7, no design keys)
- **Archetype**: pricing_engine + temporal_windowing; flat topology (api_prefix `/`); cyclic + branching state shapes; peer_roles; immediate consistency. Layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, derived_field_reconciliation.
- **13 entities**: Customer, Technician, Route, Property, ServiceQuote, QuoteLineItem, RecurringPlan, Visit, CrewAssignment, WeatherWindow, PhotoSet, Invoice, SatisfactionClaim. Self-referential FK (`Visit.reclean_of_visit_id`) plus cross-aggregate FKs.
- **6 state machines**: ServiceQuote (cyclic revise loop), Visit (cyclic re-clean loop), CrewAssignment, Invoice (branching dispute/void), SatisfactionClaim, RecurringPlan.
- **8 calculations**: chemical_dose (3-input nested min/max tiered), quote_line_total (round-per-line-then-sum, pinned), quote_total + quote_travel_surcharge (pinned eval order / threshold), visit_provisional_cost vs visit_final_cost (dual-variant), technician_risk_score (projected vs chronological dual-variant), invoice_loyalty_discount.
- **15 validations** (priority-ordered, incl. split safety checks P11 reserve-ladder / P11.5 confirm-insurance), **56 endpoints** (incl. `/_clock/set_current_utc` defaulting to 2026-04-01T00:00:00Z), **27 errors**, **4 roles** (Dispatcher/BillingAdmin opaque; FieldTech→Technician, Customer→Customer entity-backed), **1 concurrency rule** (`quote-create-stale-property`, OCC on Property.version, 412).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** — 9 rule_ids × **2 instances = 18 total**, covering all nine §0.5 rules with differentiated pairs.

**SCAFFOLD_CORNER_DESIGN.yaml** — **39 active instances + 5 `excluded_because` stubs** across all 9 claim-extraction sections. All 5 stub references resolve to named §1.8 instances.

Downstream note: endpoint count (56) exceeds Expert guideline band (20–32) because the 13-entity flat topology requires create + single-GET + filtered-list per entity for FK reverse-reachability.

## Step 3: Copy Shared Files — 2026-06-26T18:44:38.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-26T18:49:47.000Z

Generated `workspace/PRD.md` — a 323-line prose PRD for the Soft-Wash Exterior Cleaning API (domain `soft-wash-exterior-cleaning`, Expert-difficulty pricing-engine + temporal-windowing task with 13 entities, 6 state machines, 8 calculations, 27 errors, 4 roles, 56 endpoints).

**Structure:** §1 Introduction; §2 Global Specifications (10 subsections: RBAC, envelope, pagination, common properties & versioning, monetary/dose/rounding, OCC for both expected_property_version and expected_visit_version, existence & ordered validation pipeline, well-formedness ranges, cascades & conserved quantities, logical clock); §3 Business Logic (11 lifecycle subsections); §4 Endpoint table (all 56); §5 Error catalogue (all 27).

**Hard Contracts (all PASS):** Contract 1 Field-Name Coverage 56/56 entity fields + 47/47 endpoint identifiers; Contract 2 Rule Coverage 33/33 spot-checks (validation ordering, both OCC rules, cascades, all 8 formulas, dual-variant cost/risk modes, boundary semantics); Contract 3 §3 Path Purity 410 tokens scanned, 0 violations.

Confirmed: neither SCAFFOLD_DIFFICULTY_DESIGN.yaml nor SCAFFOLD_CORNER_DESIGN.yaml was read.

## Step 7: Run Tests and Iterate — 2026-06-26T19:34:31.000Z

All 8 parallel rounds are green: 67/67 passed in every round. No flakiness, no remaining failures. The fixes were entirely test-suite/test-helper layer (no implementation changes, no test deletions, no assertion weakening).

- Iterations run: 2 (1 baseline sweep + 1 post-fix sweep, both 8-round)
- Tests deleted: none
- Fixes applied to test_helpers/: none (the `test_helpers/api_client.py` signatures and `test_helpers/fixtures.py` were already correct; the bug was at the test-suite call sites)
- Fixes applied to test_suite/:
  - test_01_quote_pricing.py — `_draft_quote` helper + inline `add_line_item`/`send_quote` calls — added the PRD-required Dispatcher identity (`DISP`) to `api.create_customer/create_route/create_property/create_quote/add_line_item/send_quote`, which were called with no `headers` arg (PRD §2.1 + §4 require Dispatcher for these write endpoints; `ApiClient` methods take `headers` positionally).
  - test_02_boundary_precision.py — `_draft_quote` helper + inline `add_line_item`/`send_quote` calls — same headerless-call fix, added `DISP`.
  - test_04_state_machines.py — `test_quote_revision_cycle_sent_draft_sent` (`api.revise_quote`, `api.send_quote`) and `test_revise_from_draft_rejected_invalid_state` (`api.revise_quote`) — added `DISP` (PRD authorizes revise/send for Dispatcher).
  - test_07_entities_listing_errors_rbac.py — `test_create_customer_defaults`, `test_customer_id_is_server_minted_uuid`, `test_quote_line_item_is_append_only_no_version` — added `DISP` to their `api.create_customer`/`api.add_line_item` calls; and `test_list_visit_photos_subresource` — switched its setup from `setup_scheduled_visit` (no crew) to `setup_crewed_scheduled_visit` so the FieldTech is assigned to the visit before `upload_photo` (PRD §2.1: FieldTech ownership "means the technician is assigned to the visit"; the original crewless fixture made the assigned-tech precondition unsatisfiable).
- Fixes applied to implementation/: none

Root cause was a single class of test-suite authoring bug — direct `api.<write_method>(...)` calls in test functions omitting the PRD-required Dispatcher `headers` argument (16 tests), plus one fixture-usage bug where the photo-listing test built a visit without the crew assignment the FieldTech needs to upload. The RBAC negative tests already passed explicit headers and were untouched, so role-denial coverage is intact.

## Step 8: Finalize PRD — 2026-06-26T19:36:57.000Z

Ran (not skipped: Step 7 had >0 test_suite fixes). Produced `workspace/PRD_FINALIZED.md`. Step 7 made 0 implementation fixes, so nearly all `<step_7_diff>` items were pure test-call authoring bugs that traced to PRD prose already uniquely pinning the behavior — those produced no edit. Exactly one genuine PRD under-specification surfaced and was patched.

**Line counts:** PRD.md = 323 lines; PRD_FINALIZED.md = 323 lines. Delta = 0 lines (one line revised in place; small +char delta).

**Changes (one edit):**
- §2.1 (FieldTech ownership) — revise — widened the FieldTech ownership definition. PRD.md narrowly stated ownership "means the technician is assigned to the visit being started or completed." Impl enforces the assigned-to-visit (`ERR_NOT_RESOURCE_OWNER`) check on every FieldTech operation that references a visit: `start_visit` (`routes/visits.py:210-213`), `complete_visit` (`visits.py:234-237`), `upload_photo` (`visits.py:343-346`), `list_photos` (`visits.py:368-372`), `get_one_visit` (`visits.py:125-129`), and `list_visits` as a filter (`visits.py:104-109`). Revised wording covers all six paths (start/complete/upload/list photos/read visit; list_visits as filter "sees only those it is assigned to").

**Items assessed that needed NO edit:**
- Dispatcher required for `create_customer`/`create_route`/`create_property`/`create_quote`/`add_line_item`/`send_quote`/`revise_quote` (the 16 missing-Dispatcher-header test fixes): impl enforces `require_role(role, {"Dispatcher"})` on each; PRD §4 endpoint table + §3 prose already uniquely pin each to Dispatcher. Pure test-call authoring bugs, not PRD silences.

Pre-edit NO-NEW-MISMATCH search log (edit 1): subject = meaning of FieldTech "ownership" + which visit-referencing ops enforce the assigned-to-visit check; enumerated/read all FieldTech-touching paths in `routes/visits.py` (start_visit, complete_visit, upload_photo, list_photos, get_one_visit, list_visits) and confirmed no FieldTech ownership check exists on any non-visit resource (crew-assignments/technicians are Dispatcher-only); adjustment = replaced literal "started or completed" with "acted on" + explicit six-path enumeration, describing list_visits as a filter not an error, so wording is neither narrower than any path nor claims behavior on non-visit resources.

## Step 9: Complete PRD — 2026-06-26T19:40:55.000Z

Ran (always runs). Source = `workspace/PRD_FINALIZED.md` (present). Produced `workspace/PRD_COMPLETED.md` via a full PRD-vs-implementation/ scan.

**Files:** PRD_FINALIZED.md = 323 lines / 45,295 chars; PRD_COMPLETED.md = 323 lines / 46,807 chars. Char delta +1,512 (all in-paragraph inserts/revisions; no new sections).

**Counts:** ambiguity-pins = 5, mismatch-revisions = 2.

**Changes (one per edit):**
- §2.1 (RBAC) — revise — mismatch — Customer ownership-extension list omitted visits, photo sets, recurring plans, satisfaction claims; impl enforces customer ownership on those via the owning property (a Customer may act on/read a visit, its photo sets, or a claim only when the property's `customer_id` == `X-User-ID`) — `routes/visits.py:100-130,342-346,364-372`, `routes/claims.py:33-35,66-68`.
- §2.9 (Cascades/Conserved Quantities) — insert — ambiguity — PRD floored only `outstanding_balance_cents` at 0; impl also floors `scheduled_minutes` at 0 on release — `services/domain.py:31-32`.
- §3.1 (Customers) — insert — ambiguity — blocking quote/visit creation on a SUSPENDED customer raises `ERR_INVALID_STATE`, and (for quote create) is checked before the OCC version check — `routes/quotes.py:43-48`, `routes/visits.py:49-50`.
- §3.5 (Scheduling a Visit) — insert — ambiguity — "closed interval covers the visit's `scheduled_date`": impl treats the day as full UTC span `[00:00:00, 23:59:59.999999]` and requires only intersection — `routes/visits.py:151-153,171-187`.
- §3.9 (Recurring Plans) — insert — ambiguity — generated visit copies route from the property, derives `scheduled_date` from the `YYYY-MM-DD` prefix of `next_due_utc`, defaults `duration_minutes` to 120 — `routes/plans.py:104-116`.
- §3.10 (Satisfaction Guarantee) — revise — mismatch — spawned re-clean visit copies `property_id`,`quote_id`,`plan_id`,`route_id`,`scheduled_date`,`duration_minutes` from source visit and sets `billing_status` UNBILLED — `routes/claims.py:100-114`.
- §3.11 (Technician Risk Scoring) — insert — ambiguity — invalid `mode` → `ERR_INVALID_REQUEST`; `data` = `{"risk_score": <int>, "mode": <str>}` — `routes/technicians.py:71-73,97`.

Notable non-changes verified already-pinned: `/invoices/{id}/pay` legal-from set (ISSUED|DISPUTED), credit gate strict-`>` wording, per-line round-then-sum, travel-surcharge & loyalty tiers, both OCC fields, validation pipeline ordering.

Pipeline complete: all 8 stability rounds green (67/67); PRD.md → PRD_FINALIZED.md → PRD_COMPLETED.md present on disk.
