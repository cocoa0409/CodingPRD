import {
    apiClient,
    buildUserHeaders,
    handleApiResponse,
    validateErrorEnvelope,
    assertReview, createReviewAssignmentPayload, createReviewInvitationPayload,
    createConflictOfInterestPayload,
    Journal, ReviewAssignment, Review,
    ReviewStatus,
    UserRole,
    ApiErrorId,
    setupJournal,
    setupManuscript,
    setupReviewerProfile,
    setupBasicJournalScenario,
    setupCustomJournalScenario,
    setupInvitedReview,
    setupAcceptedReview,
    setupJournalInReview,
    JournalStatus,
    ManuscriptStatus,
    ReviewAssignmentStatus,
    ConflictOfInterestType
} from '../../../test-helpers';

describe('Phase 4: Business Logic Unit Tests', () => {
    const journalEditorHeaders = buildUserHeaders('editor-1', UserRole.JournalEditor);
    const sectionEditorHeaders = buildUserHeaders('se-1', UserRole.SectionEditor);
    const managingEditorHeaders = buildUserHeaders('me-1', UserRole.ManagingEditor);

    describe('propose-review-rule', () => {
        it('Happy path - non-extra revision review: should create review with correct state and ledger effects', async () => {
            const { journal, manuscript, reviewer, assignment } = await setupBasicJournalScenario();

            const invitationPayload = createReviewInvitationPayload(assignment.id, reviewer.id);
            const res = await apiClient.inviteReviewer(journal.id, invitationPayload, sectionEditorHeaders);
            const review = handleApiResponse<Review>(res, 201);

            assertReview(review);
            expect(review.status).toBe(ReviewStatus.INVITED);
            expect(review.in_extra_revision_cycle).toBe(false);
            expect(review.provisional_prestige_cost).toBe(1);

            const assignmentCheckRes = await apiClient.getReviewAssignment(journal.id, manuscript.id, assignment.id, journalEditorHeaders);
            const updatedAssignment = handleApiResponse<ReviewAssignment>(assignmentCheckRes, 200);
            expect(updatedAssignment.status).toBe(ReviewAssignmentStatus.INVITED);

            const journalCheckRes = await apiClient.getJournal(journal.id, journalEditorHeaders);
            const updatedJournal = handleApiResponse<Journal>(journalCheckRes, 200);
            expect(updatedJournal.prestige_balance).toBe(journal.total_prestige - 11);
            expect(updatedJournal.desk_reject_risk_score).toBe(0);
        });

        it('Extra revision review: should apply 20-point risk penalty and 1.5x prestige cost', async () => {
            const { journal, manuscript, reviewer } = await setupCustomJournalScenario(
                { total_prestige: 1000 },
                {},
                ManuscriptStatus.PENDING_REVIEW
            );

            for (let i = 0; i < 3; i++) {
                const assignmentPayload = createReviewAssignmentPayload({ required_expertise: 'Feline Psychology' });
                await apiClient.createReviewAssignment(journal.id, manuscript.id, assignmentPayload, sectionEditorHeaders);
            }

            const journalBeforeRes = await apiClient.getJournal(journal.id, journalEditorHeaders);
            const journalBefore = handleApiResponse<Journal>(journalBeforeRes, 200);

            const extraAssignmentPayload = createReviewAssignmentPayload({ required_expertise: 'Feline Psychology' });
            const extraAssignmentRes = await apiClient.createReviewAssignment(journal.id, manuscript.id, extraAssignmentPayload, sectionEditorHeaders);
            const extraAssignment = handleApiResponse<ReviewAssignment>(extraAssignmentRes, 201);

            const invitationPayload = createReviewInvitationPayload(extraAssignment.id, reviewer.id);
            const res = await apiClient.inviteReviewer(journal.id, invitationPayload, sectionEditorHeaders);
            const review = handleApiResponse<Review>(res, 201);

            expect(review.in_extra_revision_cycle).toBe(true);
            expect(review.provisional_prestige_cost).toBe(1.5);

            const journalAfterRes = await apiClient.getJournal(journal.id, journalEditorHeaders);
            const journalAfter = handleApiResponse<Journal>(journalAfterRes, 200);
            expect(journalAfter.desk_reject_risk_score).toBe(journalBefore.desk_reject_risk_score + 20);
            expect(journalAfter.prestige_balance).toBe(journalBefore.prestige_balance - 1.5);
        });

        it('Extra revision review - insufficient prestige: should reject review when provisional cost with revision penalty exceeds prestige', async () => {
            const journal = await setupJournal({ total_prestige: 11 });
            const manuscript = await setupManuscript(journal.id);
            const reviewer = await setupReviewerProfile(journal.id, { expertise_areas: ['Feline Psychology'] });

            await apiClient.beginReview(journal.id, journalEditorHeaders);

            const firstAssignmentPayload = createReviewAssignmentPayload({ required_expertise: 'Feline Psychology' });
            await apiClient.createReviewAssignment(journal.id, manuscript.id, firstAssignmentPayload, sectionEditorHeaders);

            await apiClient.updateManuscript(journal.id, manuscript.id, { status: ManuscriptStatus.PENDING_REVIEW }, journalEditorHeaders);

            for (let i = 1; i < 3; i++) {
                const assignmentPayload = createReviewAssignmentPayload({ required_expertise: 'Feline Psychology' });
                await apiClient.createReviewAssignment(journal.id, manuscript.id, assignmentPayload, sectionEditorHeaders);
            }

            const extraAssignmentPayload = createReviewAssignmentPayload({ required_expertise: 'Feline Psychology' });
            const extraAssignmentRes = await apiClient.createReviewAssignment(journal.id, manuscript.id, extraAssignmentPayload, sectionEditorHeaders);
            const extraAssignment = handleApiResponse<ReviewAssignment>(extraAssignmentRes, 201);

            const invitationPayload = createReviewInvitationPayload(extraAssignment.id, reviewer.id);
            const res = await apiClient.inviteReviewer(journal.id, invitationPayload, sectionEditorHeaders);

            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_PRESTIGE });
        });

        it('Journal not in review: should reject creating review assignment when journal is not in IN_REVIEW state', async () => {
            const journal = await setupJournal();
            const manuscript = await setupManuscript(journal.id);
            const reviewer = await setupReviewerProfile(journal.id);

            const assignmentPayload = createReviewAssignmentPayload();
            const assignmentRes = await apiClient.createReviewAssignment(journal.id, manuscript.id, assignmentPayload, sectionEditorHeaders);

            validateErrorEnvelope(assignmentRes, { expectedErrorId: ApiErrorId.ERR_JOURNAL_NOT_IN_REVIEW });
        });

        it('Assignment belongs to different journal: should reject review if assignment belongs to a different journal', async () => {
            const journalA = await setupJournal();
            const journalB = await setupJournal();

            const manuscriptB = await setupManuscript(journalB.id);
            const reviewerA = await setupReviewerProfile(journalA.id);

            await apiClient.beginReview(journalA.id, journalEditorHeaders);
            await apiClient.beginReview(journalB.id, journalEditorHeaders);

            const assignmentBPayload = createReviewAssignmentPayload();
            const assignmentBRes = await apiClient.createReviewAssignment(journalB.id, manuscriptB.id, assignmentBPayload, sectionEditorHeaders);
            const assignmentB = handleApiResponse<ReviewAssignment>(assignmentBRes, 201);

            const invitationPayload = createReviewInvitationPayload(assignmentB.id, reviewerA.id);
            const res = await apiClient.inviteReviewer(journalA.id, invitationPayload, sectionEditorHeaders);

            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND });
        });

        it('Assignment not PENDING_ASSIGNMENT: should reject review if assignment is not in PENDING_ASSIGNMENT state', async () => {
            const { journal, manuscript, reviewer, assignment } = await setupInvitedReview();
            const reviewer2 = await setupReviewerProfile(journal.id, { full_name: 'Dr. Claws' });

            const invitationPayload = createReviewInvitationPayload(assignment.id, reviewer2.id);
            const res = await apiClient.inviteReviewer(journal.id, invitationPayload, sectionEditorHeaders);

            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_PENDING });
        });

        it('Reviewer Profile belongs to different journal: should reject review if reviewer belongs to a different journal', async () => {
            const journalA = await setupJournal();
            const journalB = await setupJournal();

            const manuscriptA = await setupManuscript(journalA.id);
            const reviewerB = await setupReviewerProfile(journalB.id);

            await apiClient.beginReview(journalA.id, journalEditorHeaders);
            await apiClient.beginReview(journalB.id, journalEditorHeaders);

            const assignmentAPayload = createReviewAssignmentPayload();
            const assignmentARes = await apiClient.createReviewAssignment(journalA.id, manuscriptA.id, assignmentAPayload, sectionEditorHeaders);
            const assignmentA = handleApiResponse<ReviewAssignment>(assignmentARes, 201);

            const invitationPayload = createReviewInvitationPayload(assignmentA.id, reviewerB.id);
            const res = await apiClient.inviteReviewer(journalA.id, invitationPayload, sectionEditorHeaders);

            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_REVIEWER_NOT_FOUND });
        });

        it('Missing required expertise: should reject review if reviewer lacks required expertise', async () => {
            const { journal, manuscript, assignment } = await setupBasicJournalScenario();
            const reviewer = await setupReviewerProfile(journal.id, { expertise_areas: ['Quantum Mechanics'] });

            const invitationPayload = createReviewInvitationPayload(assignment.id, reviewer.id);
            const res = await apiClient.inviteReviewer(journal.id, invitationPayload, sectionEditorHeaders);

            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_EXPERTISE_MISMATCH });
        });

        it('Positive expertise match: should create review if reviewer has required expertise', async () => {
            const { journal, manuscript, assignment } = await setupBasicJournalScenario();
            const reviewer = await setupReviewerProfile(journal.id, { expertise_areas: ['Feline Psychology', 'Neuroscience'] });

            const invitationPayload = createReviewInvitationPayload(assignment.id, reviewer.id);
            const res = await apiClient.inviteReviewer(journal.id, invitationPayload, sectionEditorHeaders);
            const review = handleApiResponse<Review>(res, 201);

            assertReview(review);
            expect(review.assignment_id).toBe(assignment.id);
            expect(review.reviewer_id).toBe(reviewer.id);
        });

        it('Reviewer concurrency violation: should reject review if reviewer is overloaded', async () => {
            const journal = await setupJournal();
            const reviewer = await setupReviewerProfile(journal.id);
            const manuscripts = [];
            for (let i = 0; i < 6; i++) {
                manuscripts.push(await setupManuscript(journal.id, { title: `Paper ${i}` }));
            }

            await apiClient.beginReview(journal.id, journalEditorHeaders);

            const assignments = [];
            for (const manuscript of manuscripts) {
                const assignmentPayload = createReviewAssignmentPayload();
                const assignmentRes = await apiClient.createReviewAssignment(journal.id, manuscript.id, assignmentPayload, sectionEditorHeaders);
                assignments.push(handleApiResponse<ReviewAssignment>(assignmentRes, 201));
            }

            for (let i = 0; i < 5; i++) {
                const invitationPayload = createReviewInvitationPayload(assignments[i].id, reviewer.id);
                const inviteRes = await apiClient.inviteReviewer(journal.id, invitationPayload, sectionEditorHeaders);
                const review = handleApiResponse<Review>(inviteRes, 201);
                expect(review.status).toBe(ReviewStatus.INVITED);
            }

            const res = await apiClient.inviteReviewer(journal.id, createReviewInvitationPayload(assignments[5].id, reviewer.id), sectionEditorHeaders);
            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_REVIEWER_OVERLOADED });
        });

        it('Institutional conflict of interest: should reject review if reviewer has institutional conflict', async () => {
            const { journal, manuscript, assignment } = await setupBasicJournalScenario();
            const reviewer1 = await setupReviewerProfile(journal.id, { full_name: 'Reviewer One', institution: 'UCLA' });
            const reviewer2 = await setupReviewerProfile(journal.id, { full_name: 'Reviewer Two', institution: 'UCLA' });

            await apiClient.createConflictOfInterest(journal.id, createConflictOfInterestPayload(reviewer1.id, reviewer2.id, { conflict_type: ConflictOfInterestType.INSTITUTIONAL }), journalEditorHeaders);

            const res = await apiClient.inviteReviewer(journal.id, createReviewInvitationPayload(assignment.id, reviewer1.id), sectionEditorHeaders);

            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_INSTITUTIONAL_CONFLICT });
        });

        it('Prior collaboration conflict: should reject review if reviewer has prior collaboration conflict', async () => {
            const { journal, manuscript, assignment } = await setupBasicJournalScenario();
            const reviewer1 = await setupReviewerProfile(journal.id, { full_name: 'Reviewer One' });
            const reviewer2 = await setupReviewerProfile(journal.id, { full_name: 'Reviewer Two' });

            await apiClient.createConflictOfInterest(journal.id, createConflictOfInterestPayload(reviewer1.id, reviewer2.id, { conflict_type: ConflictOfInterestType.PRIOR_COLLABORATION }), journalEditorHeaders);

            const res = await apiClient.inviteReviewer(journal.id, createReviewInvitationPayload(assignment.id, reviewer1.id), sectionEditorHeaders);

            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_PRIOR_COLLABORATION });
        });

        it('Insufficient prestige: should reject review if cost exceeds remaining prestige', async () => {
            const journal = await setupJournal({ total_prestige: 10 });
            const manuscript = await setupManuscript(journal.id);
            const reviewer = await setupReviewerProfile(journal.id);

            await apiClient.beginReview(journal.id, journalEditorHeaders);

            const assignmentPayload = createReviewAssignmentPayload();
            const assignmentRes = await apiClient.createReviewAssignment(journal.id, manuscript.id, assignmentPayload, sectionEditorHeaders);
            const assignment = handleApiResponse<ReviewAssignment>(assignmentRes, 201);

            await apiClient.updateManuscript(journal.id, manuscript.id, { status: ManuscriptStatus.PENDING_REVIEW }, journalEditorHeaders);

            const res = await apiClient.inviteReviewer(journal.id, createReviewInvitationPayload(assignment.id, reviewer.id), sectionEditorHeaders);

            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_PRESTIGE });
        });

        it('Risk threshold breached: should reject extra revision review when risk score is at threshold', async () => {
            const journal = await setupJournal({ total_prestige: 1000 });
            const reviewer = await setupReviewerProfile(journal.id);
            const manuscript = await setupManuscript(journal.id);

            for (let i = 0; i < 18; i++) {
                await setupManuscript(journal.id, { is_fast_track_submission: true, title: `Fast Track ${i}` });
            }

            await apiClient.beginReview(journal.id, journalEditorHeaders);

            for (let i = 0; i < 3; i++) {
                const assignmentPayload = createReviewAssignmentPayload();
                await apiClient.createReviewAssignment(journal.id, manuscript.id, assignmentPayload, sectionEditorHeaders);
            }

            const extraAssignmentPayload = createReviewAssignmentPayload();
            const extraAssignmentRes = await apiClient.createReviewAssignment(journal.id, manuscript.id, extraAssignmentPayload, sectionEditorHeaders);
            const extraAssignment = handleApiResponse<ReviewAssignment>(extraAssignmentRes, 201);

            const res = await apiClient.inviteReviewer(journal.id, createReviewInvitationPayload(extraAssignment.id, reviewer.id), sectionEditorHeaders);

            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_RISK_THRESHOLD_BREACHED });
        });
    });

    describe('accept-review', () => {
        it('Happy path: should accept review when invitation is valid', async () => {
            const { journal, manuscript, review } = await setupInvitedReview();

            const acceptRes = await apiClient.acceptReview(journal.id, review.id, journalEditorHeaders);
            const acceptedReview = handleApiResponse<Review>(acceptRes, 200);

            expect(acceptedReview.status).toBe(ReviewStatus.ACCEPTED);

            const assignmentCheckRes = await apiClient.getReviewAssignment(journal.id, manuscript.id, review.assignment_id, journalEditorHeaders);
            const assignedAssignment = handleApiResponse<ReviewAssignment>(assignmentCheckRes, 200);
            expect(assignedAssignment.status).toBe(ReviewAssignmentStatus.ASSIGNED);
        });

        it('Cannot accept a review not in INVITED state', async () => {
            const { journal, review } = await setupAcceptedReview();

            const res = await apiClient.acceptReview(journal.id, review.id, journalEditorHeaders);

            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_REVIEW_LIFECYCLE_STATE_INVALID });
        });
    });

    describe('cancel-review', () => {
        it('should revert assignment to PENDING_ASSIGNMENT and restore prestige/risk when cancelling an INVITED review', async () => {
            const { journal, manuscript, assignment, review } = await setupInvitedReview();
            const initialJournalState = await apiClient.getJournal(journal.id, journalEditorHeaders).then(r => handleApiResponse<Journal>(r, 200));

            const cancelRes = await apiClient.cancelReview(journal.id, review.id, journalEditorHeaders);
            const cancelledReview = handleApiResponse<Review>(cancelRes, 200);
            expect(cancelledReview.status).toBe(ReviewStatus.CANCELLED);

            const assignmentCheckRes = await apiClient.getReviewAssignment(journal.id, manuscript.id, assignment.id, journalEditorHeaders);
            const revertedAssignment = handleApiResponse<ReviewAssignment>(assignmentCheckRes, 200);
            expect(revertedAssignment.status).toBe(ReviewAssignmentStatus.PENDING_ASSIGNMENT);

            const finalJournalState = await apiClient.getJournal(journal.id, journalEditorHeaders).then(r => handleApiResponse<Journal>(r, 200));
            expect(finalJournalState.prestige_balance).toBe(initialJournalState.prestige_balance + review.provisional_prestige_cost);
            expect(finalJournalState.desk_reject_risk_score).toBe(initialJournalState.desk_reject_risk_score);
        });

        it('should revert assignment to PENDING_ASSIGNMENT and restore prestige when cancelling an ACCEPTED review', async () => {
            const { journal, manuscript, assignment, review } = await setupAcceptedReview();
            const initialJournalState = await apiClient.getJournal(journal.id, journalEditorHeaders).then(r => handleApiResponse<Journal>(r, 200));

            const cancelRes = await apiClient.cancelReview(journal.id, review.id, journalEditorHeaders);
            const cancelledReview = handleApiResponse<Review>(cancelRes, 200);
            expect(cancelledReview.status).toBe(ReviewStatus.CANCELLED);

            const assignmentCheckRes = await apiClient.getReviewAssignment(journal.id, manuscript.id, assignment.id, journalEditorHeaders);
            const revertedAssignment = handleApiResponse<ReviewAssignment>(assignmentCheckRes, 200);
            expect(revertedAssignment.status).toBe(ReviewAssignmentStatus.PENDING_ASSIGNMENT);

            const finalJournalState = await apiClient.getJournal(journal.id, journalEditorHeaders).then(r => handleApiResponse<Journal>(r, 200));
            expect(finalJournalState.prestige_balance).toBe(initialJournalState.prestige_balance + review.provisional_prestige_cost);
            expect(finalJournalState.desk_reject_risk_score).toBe(initialJournalState.desk_reject_risk_score);
        });

        it('should revert assignment to PENDING_ASSIGNMENT and restore prestige when cancelling a SUBMITTED review', async () => {
            const { journal, manuscript, assignment, review } = await setupAcceptedReview();
            await apiClient.submitReview(journal.id, review.id, journalEditorHeaders);
            const initialJournalState = await apiClient.getJournal(journal.id, journalEditorHeaders).then(r => handleApiResponse<Journal>(r, 200));

            const cancelRes = await apiClient.cancelReview(journal.id, review.id, journalEditorHeaders);
            const cancelledReview = handleApiResponse<Review>(cancelRes, 200);
            expect(cancelledReview.status).toBe(ReviewStatus.CANCELLED);

            const assignmentCheckRes = await apiClient.getReviewAssignment(journal.id, manuscript.id, assignment.id, journalEditorHeaders);
            const revertedAssignment = handleApiResponse<ReviewAssignment>(assignmentCheckRes, 200);
            expect(revertedAssignment.status).toBe(ReviewAssignmentStatus.PENDING_ASSIGNMENT);

            const finalJournalState = await apiClient.getJournal(journal.id, journalEditorHeaders).then(r => handleApiResponse<Journal>(r, 200));
            expect(finalJournalState.prestige_balance).toBe(initialJournalState.prestige_balance + review.provisional_prestige_cost);
            expect(finalJournalState.desk_reject_risk_score).toBe(initialJournalState.desk_reject_risk_score);
        });
    });

    describe('initiate-publication', () => {
        it('should allow publication initiation when all reviews are resolved', async () => {
            const journal = await setupJournal();
            const manuscript = await setupManuscript(journal.id);
            const reviewer = await setupReviewerProfile(journal.id);
            await apiClient.beginReview(journal.id, journalEditorHeaders);

            const createAssignment = () => {
                const payload = createReviewAssignmentPayload();
                return apiClient.createReviewAssignment(journal.id, manuscript.id, payload, sectionEditorHeaders)
                    .then(r => handleApiResponse<ReviewAssignment>(r, 201));
            };

            const inviteReviewer = (assignmentId: string) => {
                const payload = createReviewInvitationPayload(assignmentId, reviewer.id);
                return apiClient.inviteReviewer(journal.id, payload, sectionEditorHeaders)
                    .then(r => handleApiResponse<Review>(r, 201));
            };

            const assignment1 = await createAssignment();
            const review1 = await inviteReviewer(assignment1.id);
            await apiClient.acceptReview(journal.id, review1.id, journalEditorHeaders);
            await apiClient.submitReview(journal.id, review1.id, journalEditorHeaders);

            const assignment2 = await createAssignment();
            const review2 = await inviteReviewer(assignment2.id);
            await apiClient.declineReview(journal.id, review2.id, journalEditorHeaders);

            const assignment3 = await createAssignment();
            const review3 = await inviteReviewer(assignment3.id);
            await apiClient.cancelReview(journal.id, review3.id, journalEditorHeaders);

            const res = await apiClient.initiatePublication(journal.id, journalEditorHeaders);
            const pubPendingJournal = handleApiResponse<Journal>(res, 200);
            expect(pubPendingJournal.status).toBe(JournalStatus.PUBLICATION_PENDING);
        });

        it('should reject publication initiation if an unresolved review still exists', async () => {
            const { journal } = await setupInvitedReview();

            const res = await apiClient.initiatePublication(journal.id, journalEditorHeaders);
            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_UNRESOLVED_REVIEWS_EXIST });
        });

        it('should reject publication initiation if journal is not IN_REVIEW', async () => {
            const journal = await setupJournal();

            const res = await apiClient.initiatePublication(journal.id, journalEditorHeaders);
            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_JOURNAL_LIFECYCLE_STATE_INVALID });
        });
    });

    describe('finalize-publication', () => {
        it('should move journal to ARCHIVED and review to PUBLISHED on successful finalization', async () => {
            const { journal, review } = await setupAcceptedReview();
            await apiClient.submitReview(journal.id, review.id, journalEditorHeaders);
            await apiClient.initiatePublication(journal.id, journalEditorHeaders);

            const finalizeRes = await apiClient.finalizePublication(journal.id, managingEditorHeaders);
            const finalJournal = handleApiResponse<Journal>(finalizeRes, 200);

            expect(finalJournal.status).toBe(JournalStatus.ARCHIVED);

            const billedReviewRes = await apiClient.getReview(journal.id, review.id, journalEditorHeaders);
            const billedReview = handleApiResponse<Review>(billedReviewRes, 200);
            expect(billedReview.status).toBe(ReviewStatus.PUBLISHED);
            expect(billedReview.final_prestige_cost).toBe(review.provisional_prestige_cost);
        });

        it('should reject finalization if project is not PUBLICATION_PENDING', async () => {
            const journal = await setupJournalInReview();
            const res = await apiClient.finalizePublication(journal.id, managingEditorHeaders);
            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_JOURNAL_NOT_PENDING_PUBLICATION });
        });
    });
});
