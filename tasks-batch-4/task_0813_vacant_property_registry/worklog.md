# Worklog — task_0813_vacant_property_registry

## Step 1: Create task directory — 2026-07-10T00:00:00.000Z

Created `tasks/task_0813_vacant_property_registry/` and `tasks/task_0813_vacant_property_registry/workspace/` (pre-assigned directory; no index auto-scan).

## Step 2: Generate scaffold (Expert) — 2026-07-10T08:35:00.000Z

All three artifacts are complete, parse cleanly under `yaml.safe_load`, and pass `scaffold_lint.py` with `VERDICT: clean lint`.

## Summary

Generated the Expert-level scaffold for **task_0813_vacant_property_registry** (archetype: compliance/audit × ledger-reconciliation; flat topology; parallel state axes; peer roles).

Files written to `/home/ubuntu/github/CodingPRD/tasks/task_0813_vacant_property_registry/`:
- `SCAFFOLD.yaml` (§1.0–§1.7 + concurrency)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9)

### Counts
| Element | Count |
|---|---|
| Entities | 11 (Registrant, Property, MaintenanceStandard, Inspection, Violation, Fine, Lien, AbatementOrder, ReceivershipReferral, DemolitionListing, LedgerEntry) |
| State machines | 9 (Property registration axis + Property foreclosure axis as parallel dimensions, Violation, Fine, Lien, Inspection, AbatementOrder, ReceivershipReferral, DemolitionListing) |
| Calculations | 7 (registration_fee, fine_accrual [dual-variant], lien_payoff [dual-variant], property_outstanding_balance, property_lien_balance, demolition_priority_score, cost_recovery_charge) |
| Validations | 21 (priority-ordered) |
| Endpoints | 38 |
| Errors | 28 |
| Roles | 4 (Anonymous, Registrant [entity_backed], CodeOfficer [opaque], ProgramAdmin [opaque]) |
| Concurrency rules | 1 (OCC renew-stale-property) |
| §1.8 rule instances | 18 (9 rules × 2) |
| §1.9 corner instances | 33 (26 active + 7 `excluded_because` stubs) |

### Notes
- All numeric asserts (fine accrual tiers, lien payoff round-per-day vs sum-then-round = 30800 vs 30822, cost recovery, demolition priority = 44, ledger conservation) were computed in Python and written as literals.
- Every difficulty rule's differentiation clause is honored: dual-variant on **different entity domains** (Fine vs Lien); combinatorial in **different modes** (weighted non-linear (a) vs rounding-order (b)); non-linear machines on **different entities** (Property parallel-axes vs Violation cyclic); cascades from **different triggers** (fine-assess→suspend vs demolish→void→waive), both depth 3; priority conflicts across **different category pairs** (state/fiscal, existence/temporal); boundaries on **different metrics/endpoints** (fine days-overdue vs demolition violation-count); cross-entity deps across **different pairs** (Referral↔Property, Abatement↔Violation); overlaps with **different interval semantics** (inspector half-open vs property closed+24h-buffer); invariants over **different conserved quantities** (per-fine ledger net vs lien principal pool).
- Hard constraint respected: no sibling task directories were read; scaffold derived solely from the scenario + skill spec.
- One caveat worth flagging: endpoint count is 38, slightly above the Expert guideline band (20–32). The scenario spans 8 distinct statutory workflows and the benchmark mandates FK reverse-reachability for every child entity; I already consolidated hard (generic `transition` endpoints, sub-resource reverse-reach for leaf entities, auto-suspend/reinstate instead of explicit endpoints). The difficulty is carried by entity coupling/calculations, not surface volume.

## Step 3: Copy shared files — 2026-07-10T08:36:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0813_vacant_property_registry/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-07-10T08:45:00.000Z

Generated `workspace/PRD.md` (290 lines) from the scaffold, written incrementally section by section.

**Structure:**
- §1 Introduction (3 paragraphs — compliance-audit ledger framing)
- §2 Global Specifications, 10 subsections: 2.1 RBAC, 2.2 Response Structure (verbatim), 2.3 Pagination, 2.4 Identity/Timestamps/Versioning, 2.5 Logical Clock, 2.6 Ledger & Derived Balances, 2.7 Precision & Rounding, 2.8 OCC on Renewal, 2.9 Dual-Axis State & Cascade Consistency, 2.10 Nested Path Resolution & Validation Ordering
- §3 Business Logic, 10 lifecycle subsections (party/property onboarding, foreclosure, standards/inspections, violations, fines, liens, abatement, receivership, demolition, reporting)
- §4 Endpoint table (4 columns), §5 Error table (2 columns)

**Coverage confirmation (all mechanically verified):**
- Endpoints: **38** rows in §4 table = all 38 scaffold endpoints; each behavior derivable from §3 prose
- Errors: **28** in §5 table, and all **28** also appear in §2/§3 narrative near their trigger conditions
- Calculations: all **7** expressed as precise business prose with no pseudocode/operators/fuzzy words — registration_fee (tiered base+surcharge), fine_accrual (dual-rate tiers, 3x cap, provisional/finalized variants), lien_payoff (round-per-day-then-sum vs sum-then-round variants), property_outstanding_balance, property_lien_balance, demolition_priority_score (4 capped components), cost_recovery_charge (tiered fee + reimbursement)
- Validations: all **21** covered with relative priority orderings stated
- State machines: all **9** — every transition (including cyclic violation reopen, fine dispute-revert, and both demolish/redeem cascade edges) named with from→to state pairs and side effects
- Roles: all **4** (Anonymous, Registrant, CodeOfficer, ProgramAdmin)

**Hard Contract reports:** Contract 1 (Field-Name Coverage, 78 names) PASS; Contract 2 (Rule Coverage incl. OCC + cascades) PASS; Contract 3 (§3 Path Purity) PASS.

Orchestrator cross-check: all 38 scaffold endpoint paths and all 28 error IDs appear verbatim in PRD.md.

## Step 5: Generate unit tests — 2026-07-10T09:00:00.000Z

Generated complete test infrastructure and suite for `task_0813_vacant_property_registry`.

**Stage 1 — `test_helpers/` (9 files):**
- `types.py` — enums + entity TypedDicts (MaintenanceStandard and LedgerEntry correctly carry only `id`/`created_at`; all others carry the full `version`/`updated_at` triple)
- `api_client.py` — one method per endpoint in PRD Section 4
- `api_errors.py` — 28-error catalog + HTTP-status map registered with the framework
- `constants.py`, `factories.py`, `assertions.py`, `test_users.py` (with mandatory `make_registrant_headers(user_id)` for the sole `entity_backed:Registrant` role), `fixtures.py` (granular + composite helpers: `setup_open_violation`, `setup_escalated_violation`, `setup_assessed_fine`, `setup_recorded_lien`, `setup_property_with_n_open_violations`), and `__init__.py` barrel export

**Stage 2 — `test_suite/` (conftest + 8 test files, 62 tests):**
Organized by domain concern (registration/validation, RBAC, inspections/violations, fines/accrual, liens, foreclosure/receivership/abatement, demolition, renewal/reporting).

**Coverage (design-index-only, verified):**
- **All 18 difficulty instances → exactly 2 tests each (36 tests).**
- **All 26 non-stub corner instances → exactly 1 test each (26 tests).**
- The 7 `excluded_because:` error stubs were NOT translated; their `difficulty_instance` cross-references all resolve to real difficulty instances.

**Instances translated vs skipped:** 44 instances translated, 0 skipped. Every asserted rule has verbatim PRD coverage (citations spot-checked with literal grep against `PRD.md`) and is uniquely derivable. One design assertion was deliberately narrowed rather than dropped: for `fine_provisional_vs_finalized_accrual` I asserted `fine_a.finalized_amount_cents == 45000` (uniquely derivable) instead of the recipe's `accrued_amount_cents == 45000` on the *paid* fine, since PRD leaves post-settlement provisional accrual open — the instance still gets its required 2 tests via the finalized-freeze and provisional-cap assertions.

**Bug fixed during generation:** `create_property_payload` was overwriting the auto-generated unique `parcel_id` with `None` when callers passed `parcel_id=None` (the "auto" sentinel), which would have failed every property creation; rewritten to treat a `None` override as "auto-generate".

## Step 6: Generate implementation — 2026-07-10T09:16:00.000Z

Built a complete Python + Flask implementation in `workspace/implementation/`.

**Files written (12):**
- `start.sh` — foreground launcher, `exec python3 app.py`, guarded `pip install` (only when Flask missing), binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — `flask>=3.0,<4.0`
- `app.py` — Flask app (`static_folder=None` so exactly 38 rules register), error handlers, entry point
- `store.py` — in-memory dicts + logical clock (default `2026-03-01T00:00:00Z`); empty on every boot, no seeding
- `util.py` — ISO-8601 parse/format (3-digit ms + `Z`), floor-days, `ROUND_HALF_UP` helpers (Decimal, never float)
- `envelope.py` — `meta`/`response_type`/`data` success + error envelopes, `req_` request ids, error→HTTP catalogue
- `reqhelp.py` — auth (`X-User-ID`/`X-User-Role`), RBAC, ownership, body validation, pagination (`limit`/`offset`/`total_count`/`has_more`)
- `calc.py` — registration fee, tiered fine accrual, dual-variant lien payoff (round-per-day-then-sum vs sum-then-round), cost recovery, demolition priority
- `services.py` — ledger posting, auto-suspend/reinstate, fine settlement, lien recording, demolish/redeem cascades, derived totals
- `serialize.py` — per-entity serializers with computed fields resolved at read time
- `routes_core.py` / `routes_enf.py` — all 38 route handlers

**Registered route count: 38 vs 38 in SCAFFOLD.yaml — exact match.**

**Boot check passed:** server boots from a fresh process, responds to HTTP, and store is confirmed empty at boot (no seeded entities). A 35-assertion end-to-end run passed, covering auth/RBAC/ownership (403 on non-owner), OCC stale-version (412), license-required, type-mismatch, duplicate-parcel, inspector double-booking (half-open, touching allowed), cure-period/escalation, tiered fine accrual (46000 at 31 days), lien conversion + payoff divergence (accrued 50745 vs quoted 50600), and ledger conservation (balance returns to 30000 after lien).

Key PRD-fidelity decisions: FK-existence checked before body well-formedness (per §2.10 ordering); Registrant ownership enforced on existing-resource actions (renew, foreclosure, fine transition, lien pay) but not on property creation (to avoid clobbering the `ERR_REGISTRANT_NOT_FOUND` path); input datetimes echoed verbatim while server-stamped timestamps use the logical clock; `created_at`/`updated_at` use wall-clock audit time as the PRD distinguishes them from business timestamps.

Orchestrator cross-check: `app.py` present, all 12 impl modules `ast.parse` clean, 62 test functions across 8 test files.

## Step 7: Run tests and iterate — 2026-07-10T09:35:00.000Z

Clean 8-round sweep achieved: all 8 rounds pass 62/62.

## Summary

**Iterations run:** 2 full 8-round sweeps (two waves of 4 each).

**Baseline:** 61/62 in every round, one deterministic failure: `test_anonymous_cannot_read_property_returns_unauthenticated` (`test_suite/test_02_rbac.py`) — expected `ERR_UNAUTHENTICATED`, implementation returned `ERR_UNAUTHORIZED`.

**Tests deleted:** none.

**Fixes applied to `test_suite/`:**
- `test_02_rbac.py` — `test_anonymous_cannot_read_property_returns_unauthenticated`: relaxed the exact-error assertion `validate_error(resp, ERR_UNAUTHENTICATED)` to `validate_error_is_one_of(resp, [ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED])`. This is an ERROR-PRECEDENCE / role-classification non-unique-derivability case (STEP 1b), not an implementation bug.

**Reasoning:** PRD §2.1 (workspace/PRD.md line 15) says a request whose `X-User-Role` "is not one of the roles enumerated below" gets `ERR_UNAUTHENTICATED`. But line 19 explicitly enumerates `Anonymous` as a role, and line 24 states "a caller whose role is unknown always sees `ERR_UNAUTHENTICATED`, never `ERR_UNAUTHORIZED`." Because `Anonymous` is a *known/enumerated* role, a faithful PRD-only implementer can reasonably conclude a well-formed Anonymous GET passes authentication and fails authorization → `ERR_UNAUTHORIZED` (which the implementation does, treating `Anonymous` as a `KNOWN_ROLES` member in `reqhelp.py`). Another faithful reader treats "Anonymous = unauthenticated caller" → `ERR_UNAUTHENTICATED`. Both errors are named in the PRD and both readings are PRD-supported, so the exact-error assertion is not uniquely derivable; the permitted `validate_error_is_one_of` relaxation preserves the meaningful coverage (an Anonymous caller cannot read a property; it must get an auth error, not a 200) without weakening it against the implementation.

**Fixes applied to `test_helpers/`:** none.
**Fixes applied to `implementation/`:** none — the implementation's `ERR_UNAUTHORIZED` is a PRD-faithful reading.

Final result: 8/8 rounds green, 62/62 tests passing.

Orchestrator re-verification: re-ran the full 8-round sweep (two waves of 4) independently; rounds 1–8 all report `passed=62 total=62 failed=0 errors=0`. `results.{1..8}.json` regenerated in `workspace/implementation/`.

## Step 8: Finalize PRD — 2026-07-10T09:50:00.000Z

**Line counts:** PRD.md = 290 lines; PRD_FINALIZED.md = 290 lines (edit was inline within one bullet). Character delta ≈ +560 chars on the §2.1 Anonymous bullet; line-count %-delta = 0%.

**Changes (one bullet per change):**
- §2.1 (Anonymous role bullet) — insert — appended a sentence pinning that a well-formed `X-User-Role: Anonymous` request (both auth headers present) passes authentication because `Anonymous` is an enumerated/known role, and any non-self-registration endpoint then rejects it at authorization with `ERR_UNAUTHORIZED` (not `ERR_UNAUTHENTICATED`) — `implementation/reqhelp.py:7,15-18` (`Anonymous ∈ KNOWN_ROLES`; role∉allowed → `ERR_UNAUTHORIZED`), exercised by `routes_core.py:101` (`get_property` calls `authenticate(READ_ROLES)`, which excludes Anonymous).

**Per-edit pre-edit search log:**
- Edit 1 — Anonymous auth classification
  - (a) Subject: how the `Anonymous` role is classified across the two-stage auth pipeline (authentication vs authorization), and which error a non-self-registration Anonymous request yields.
  - (b) Impl paths enumerated/read:
    - `reqhelp.py:7` `KNOWN_ROLES` includes `"Anonymous"`; `reqhelp.py:8` `READ_ROLES` excludes it; `reqhelp.py:11-19` `authenticate()` — requires both `role` and `uid` present AND `role ∈ KNOWN_ROLES` else `ERR_UNAUTHENTICATED`, then `role ∉ allowed_roles` → `ERR_UNAUTHORIZED`. Confirms Anonymous with both headers passes stage 1, fails stage 2.
    - `routes_core.py:36-58` `create_registrant` — the sole endpoint with NO `authenticate()` call, so self-registration needs no headers and Anonymous is never in any `allowed_roles` set. Confirms the "other than self-registration" carve-out.
    - Every other route's `authenticate(...)` call (grepped across `routes_core.py` and `routes_enf.py`) — none include `Anonymous` in allowed roles; all read endpoints use `READ_ROLES`. So Anonymous uniformly gets `ERR_UNAUTHORIZED` (given headers present), never a special-case `ERR_UNAUTHENTICATED`.
    - `test_helpers/test_users.py:11` `build_user_headers("anon-caller-1", "Anonymous")` — confirms anonymous fixtures carry both `X-User-ID` and `X-User-Role`, so `uid` is present and stage-1 passes (justifying the "both auth headers present" qualifier).
  - (c) Wording adjustment: added the qualifier "with both auth headers present" so the claim does not contradict `reqhelp.py:15` (an Anonymous request missing `X-User-ID` still yields `ERR_UNAUTHENTICATED` via the `not uid` check) and does not override the existing line-15 missing-header rule. Scoped the `ERR_UNAUTHORIZED` claim to "any endpoint other than self-registration" to stay consistent with `create_registrant` requiring no auth. Left the existing line-24 "unknown role → always `ERR_UNAUTHENTICATED`" untouched since Anonymous is a known role, not unknown.

No implementation fixes, no test deletions, and no other PRD edits were warranted — the sole Step 7 item (the relaxed `test_anonymous_cannot_read_property` assertion) traces entirely to this one PRD ambiguity, now pinned to the implementation's `ERR_UNAUTHORIZED` behavior.

## Step 9: Complete PRD — 2026-07-10T09:57:00.000Z

- Source `PRD_FINALIZED.md`: 290 lines / 52,970 chars → `PRD_COMPLETED.md`: 290 lines / 54,210 chars (char delta **+1,240**; line count unchanged — all edits are in-paragraph inserts).
- **Ambiguity-pins: 5. Mismatch-revisions: 0.** (Impl walk found no case where PRD prose actively described a *different* behavior — the gaps were all silences.)

### Changes
- **§2.3 Pagination — insert — ambiguity** — pinned that a non-integer or out-of-bounds `limit`/`offset` yields `ERR_VALIDATION`, and that ascending `created_at` order ties break by insertion order. — `reqhelp.py:73-91`, `reqhelp.py:94-96`
- **§3.1 Property Onboarding — insert — ambiguity** — pinned that property creation does *not* require the caller's `X-User-ID` to equal the supplied `registrant_id` (any existing registrant may be named), while later property actions still enforce the §2.1 ownership check. — `routes_core.py:61-97` (no owner check at create) vs `routes_core.py:126,140`, `routes_enf.py:249,320` (checks on later actions)
- **§3.5 Conversion to a lien — insert — ambiguity** — pinned that `record-lien` responds with **HTTP 201** and returns the updated fine (now `LIENED`) in `data`, not the newly created lien. — `routes_enf.py:289`
- **§3.10 Reporting — insert — ambiguity** — pinned that `by_registration_status` and `by_foreclosure_status` always carry every status key zero-filled. — `routes_core.py:223-230`
- **§3.10 Reporting — insert — ambiguity** — pinned that `demolition_listed_count` counts a property when it holds a listing in status `LISTED` or `SCHEDULED`. — `routes_core.py:233-234`

### Notes on things checked but intentionally left unchanged
- All 38 endpoint role authorizations, status codes, error precedence (§2.10), calculation formulas (fee tiers, fine accrual cap, dual lien payoff rounding, admin-fee tiers, priority score), state machines, and cascades already match the implementation exactly.
- List ordering by internal `_seq` is observationally identical to `created_at` ascending (both monotonic with insertion); pinned only the tie-break wording rather than changing the stated order.
- Missing-FK-field cases (e.g. absent `registrant_id`/`property_id` on create) yielding not-found errors are already implied by the §2.10 ordering (FK existence precedes body well-formedness), so no new prose was added there.

## Pipeline complete — 2026-07-10T09:58:00.000Z

All 9 steps finished. Final state: 62/62 tests passing across 8/8 stability rounds.
