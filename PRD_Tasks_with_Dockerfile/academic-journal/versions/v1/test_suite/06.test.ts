import {
    apiClient,
    buildUserHeaders,
    handleApiResponse,
    validateErrorEnvelope,
    setupJournal,
    setupManuscript,
    setupReviewerProfile,
    createReviewAssignmentPayload,
    createReviewInvitationPayload,
    createConflictOfInterestPayload,
    assertReview,
    assertConflictOfInterest,
    UserRole,
    Manuscript,
    ReviewerProfile,
    ReviewAssignment,
    Review,
    ConflictOfInterest,
    ReviewStatus,
    ManuscriptStatus,
    ApiErrorId,
    ConflictOfInterestType,
    setupBasicJournalScenario,
    setupInvitedReview,
    validateApiResponseStructure,
    Journal,
} from '../../../test-helpers';

describe('Phase 6: Mixed and Complex Scenarios', () => {
    const journalEditorHeaders = buildUserHeaders('jour-editor-1', UserRole.JournalEditor);
    const sectionEditorHeaders = buildUserHeaders('sect-editor-1', UserRole.SectionEditor);
    const managingEditorHeaders = buildUserHeaders('mng-editor-1', UserRole.ManagingEditor);

    describe('Conflict of Interest created after assignments', () => {
        it('should prevent re-invitation when a conflict is created after original invitations', async () => {
            const { journal, manuscript, assignment } = await setupBasicJournalScenario();
            const reviewer1 = await setupReviewerProfile(journal.id, { full_name: 'Reviewer One' });
            const reviewer2 = await setupReviewerProfile(journal.id, { full_name: 'Reviewer Two' });

            const assignment2Res = await apiClient.createReviewAssignment(journal.id, manuscript.id, createReviewAssignmentPayload(), sectionEditorHeaders);
            const assignment2 = handleApiResponse<ReviewAssignment>(assignment2Res, 201);

            const review1Res = await apiClient.inviteReviewer(journal.id, createReviewInvitationPayload(assignment.id, reviewer1.id), sectionEditorHeaders);
            const review1 = handleApiResponse<Review>(review1Res, 201);
            await apiClient.acceptReview(journal.id, review1.id, journalEditorHeaders);

            const review2Res = await apiClient.inviteReviewer(journal.id, createReviewInvitationPayload(assignment2.id, reviewer2.id), sectionEditorHeaders);
            const review2 = handleApiResponse<Review>(review2Res, 201);
            await apiClient.acceptReview(journal.id, review2.id, journalEditorHeaders);

            await apiClient.createConflictOfInterest(journal.id, createConflictOfInterestPayload(reviewer1.id, reviewer2.id, { conflict_type: ConflictOfInterestType.PRIOR_COLLABORATION }), journalEditorHeaders);

            await apiClient.cancelReview(journal.id, review1.id, journalEditorHeaders);

            const reInviteRes = await apiClient.inviteReviewer(journal.id, createReviewInvitationPayload(assignment.id, reviewer1.id), sectionEditorHeaders);

            validateErrorEnvelope(reInviteRes, { expectedErrorId: ApiErrorId.ERR_PRIOR_COLLABORATION });
        }, 10000);

        it('should prevent invitation in both directions when a conflict is registered', async () => {
            const { journal, manuscript, assignment } = await setupBasicJournalScenario();
            const reviewer1 = await setupReviewerProfile(journal.id, { full_name: 'Reviewer A' });
            const reviewer2 = await setupReviewerProfile(journal.id, { full_name: 'Reviewer B' });

            const assignment2Res = await apiClient.createReviewAssignment(journal.id, manuscript.id, createReviewAssignmentPayload(), sectionEditorHeaders);
            const assignment2 = handleApiResponse<ReviewAssignment>(assignment2Res, 201);

            await apiClient.createConflictOfInterest(journal.id, createConflictOfInterestPayload(reviewer1.id, reviewer2.id), journalEditorHeaders);

            const invite2Res = await apiClient.inviteReviewer(journal.id, createReviewInvitationPayload(assignment.id, reviewer2.id), sectionEditorHeaders);
            validateErrorEnvelope(invite2Res, { expectedErrorId: ApiErrorId.ERR_INSTITUTIONAL_CONFLICT });

            const invite1Res = await apiClient.inviteReviewer(journal.id, createReviewInvitationPayload(assignment2.id, reviewer1.id), sectionEditorHeaders);
            validateErrorEnvelope(invite1Res, { expectedErrorId: ApiErrorId.ERR_INSTITUTIONAL_CONFLICT });
        });
    });

    describe('Cancelling a Review', () => {
        it('should revert prestige and risk for a cancelled extra-revision-cycle review', async () => {
            const { journal, manuscript, review, assignment, initialJournalState } = await setupInvitedReview({
                isExtraRevision: true,
                journalPrestige: 100
            });
            await apiClient.acceptReview(journal.id, review.id, journalEditorHeaders);

            const journalAfterInviteRes = await apiClient.getJournal(journal.id, journalEditorHeaders);
            const journalAfterInvite = handleApiResponse<Journal>(journalAfterInviteRes, 200);

            expect(journalAfterInvite.prestige_balance).toBeLessThan(initialJournalState.prestige_balance);
            expect(journalAfterInvite.desk_reject_risk_score).toBe(initialJournalState.desk_reject_risk_score + 20);

            await apiClient.cancelReview(journal.id, review.id, journalEditorHeaders);

            const journalAfterCancelRes = await apiClient.getJournal(journal.id, journalEditorHeaders);
            const journalAfterCancel = handleApiResponse<Journal>(journalAfterCancelRes, 200);

            expect(journalAfterCancel.prestige_balance).toBe(initialJournalState.prestige_balance);
            expect(journalAfterCancel.desk_reject_risk_score).toBe(initialJournalState.desk_reject_risk_score);

            const assignmentAfterRes = await apiClient.getReviewAssignment(journal.id, manuscript.id, assignment.id, sectionEditorHeaders);
            expect(handleApiResponse<ReviewAssignment>(assignmentAfterRes, 200).status).toBe('PENDING_ASSIGNMENT');
        });

        it('should revert ReviewAssignment to PENDING_ASSIGNMENT but not change Manuscript status', async () => {
            const { journal, manuscript, review } = await setupInvitedReview();
            await apiClient.acceptReview(journal.id, review.id, journalEditorHeaders);

            const manuscriptBeforeRes = await apiClient.getManuscript(journal.id, manuscript.id, sectionEditorHeaders);
            expect(handleApiResponse<Manuscript>(manuscriptBeforeRes, 200).status).toBe(ManuscriptStatus.PENDING_REVIEW);

            const cancelRes = await apiClient.cancelReview(journal.id, review.id, journalEditorHeaders);
            const cancelledReview = handleApiResponse<Review>(cancelRes, 200);
            expect(cancelledReview.status).toBe(ReviewStatus.CANCELLED);

            const assignmentAfterRes = await apiClient.getReviewAssignment(journal.id, manuscript.id, review.assignment_id, sectionEditorHeaders);
            const assignmentAfter = handleApiResponse<ReviewAssignment>(assignmentAfterRes, 200);
            expect(assignmentAfter.status).toBe('PENDING_ASSIGNMENT');

            const manuscriptAfterRes = await apiClient.getManuscript(journal.id, manuscript.id, sectionEditorHeaders);
            expect(handleApiResponse<Manuscript>(manuscriptAfterRes, 200).status).toBe(ManuscriptStatus.PENDING_REVIEW);
        });
    });

    describe('Listing Resources', () => {
        it('should list manuscripts in ascending order of creation', async () => {
            const journal = await setupJournal();
            const manuscript1 = await setupManuscript(journal.id, { title: 'Manuscript A' });
            await new Promise(resolve => setTimeout(resolve, 10));
            const manuscript2 = await setupManuscript(journal.id, { title: 'Manuscript B' });

            const listRes = await apiClient.getManuscripts(journal.id, sectionEditorHeaders);
            const manuscripts = handleApiResponse<Manuscript[]>(listRes, 200, { expectPaginated: true });

            expect(manuscripts).toHaveLength(2);
            const titles = manuscripts.map(m => m.title);
            expect(titles).toContain(manuscript1.title);
            expect(titles).toContain(manuscript2.title);
            expect(manuscripts.map(m => m.id)).toEqual([manuscript1.id, manuscript2.id]);
        });

        it('should list review assignments in ascending order of creation', async () => {
            const { journal, manuscript } = await setupBasicJournalScenario();
            const assignment1Res = await apiClient.createReviewAssignment(journal.id, manuscript.id, createReviewAssignmentPayload(), sectionEditorHeaders);
            const assignment1 = handleApiResponse<ReviewAssignment>(assignment1Res, 201);
            await new Promise(resolve => setTimeout(resolve, 10));
            const assignment2Res = await apiClient.createReviewAssignment(journal.id, manuscript.id, createReviewAssignmentPayload(), sectionEditorHeaders);
            const assignment2 = handleApiResponse<ReviewAssignment>(assignment2Res, 201);

            const listRes = await apiClient.getReviewAssignments(journal.id, manuscript.id, sectionEditorHeaders);
            const assignments = handleApiResponse<ReviewAssignment[]>(listRes, 200, { expectPaginated: true });

            expect(assignments.length).toBeGreaterThanOrEqual(2);
            const assignmentIds = assignments.map(a => a.id);
            expect(assignmentIds).toContain(assignment1.id);
            expect(assignmentIds).toContain(assignment2.id);
            const a1Index = assignments.findIndex(a => a.id === assignment1.id);
            const a2Index = assignments.findIndex(a => a.id === assignment2.id);
            expect(a1Index).toBeLessThan(a2Index);
        });

        it('should retrieve a specific review by ID', async () => {
            const { journal, review } = await setupInvitedReview();

            const getRes = await apiClient.getReview(journal.id, review.id, sectionEditorHeaders);
            const retrieved = handleApiResponse<Review>(getRes, 200);

            assertReview(retrieved);
            expect(retrieved.id).toBe(review.id);
            expect(retrieved.journal_id).toBe(journal.id);
        });

        it('should list all reviews in ascending order of creation', async () => {
            const { journal, manuscript, reviewer, assignment } = await setupBasicJournalScenario();
            const assignment2Res = await apiClient.createReviewAssignment(journal.id, manuscript.id, createReviewAssignmentPayload(), sectionEditorHeaders);
            const assignment2 = handleApiResponse<ReviewAssignment>(assignment2Res, 201);

            const review1Res = await apiClient.inviteReviewer(journal.id, createReviewInvitationPayload(assignment.id, reviewer.id), sectionEditorHeaders);
            const review1 = handleApiResponse<Review>(review1Res, 201);
            await new Promise(resolve => setTimeout(resolve, 10));
            const review2Res = await apiClient.inviteReviewer(journal.id, createReviewInvitationPayload(assignment2.id, reviewer.id), sectionEditorHeaders);
            const review2 = handleApiResponse<Review>(review2Res, 201);

            const listRes = await apiClient.getReviews(journal.id, sectionEditorHeaders);
            const reviews = handleApiResponse<Review[]>(listRes, 200, { expectPaginated: true });

            expect(reviews.length).toBeGreaterThanOrEqual(2);
            const reviewIds = reviews.map(r => r.id);
            expect(reviewIds).toContain(review1.id);
            expect(reviewIds).toContain(review2.id);
            const r1Index = reviews.findIndex(r => r.id === review1.id);
            const r2Index = reviews.findIndex(r => r.id === review2.id);
            expect(r1Index).toBeLessThan(r2Index);
        });

        it('should list all reviewer profiles in ascending order of creation', async () => {
            const journal = await setupJournal();
            const reviewerA = await setupReviewerProfile(journal.id, { full_name: 'Dr. A' });
            await new Promise(resolve => setTimeout(resolve, 10));
            const reviewerB = await setupReviewerProfile(journal.id, { full_name: 'Dr. B' });

            const listRes = await apiClient.getReviewerProfiles(journal.id, sectionEditorHeaders);
            const profiles = handleApiResponse<ReviewerProfile[]>(listRes, 200, { expectPaginated: true });

            expect(profiles).toHaveLength(2);
            const profileIds = profiles.map(p => p.id);
            expect(profileIds).toContain(reviewerA.id);
            expect(profileIds).toContain(reviewerB.id);
            expect(profiles.map(p => p.id)).toEqual([reviewerA.id, reviewerB.id]);
        });

        it('should retrieve a specific conflict of interest by ID', async () => {
            const journal = await setupJournal();
            const r1 = await setupReviewerProfile(journal.id);
            const r2 = await setupReviewerProfile(journal.id);

            const exclusionRes = await apiClient.createConflictOfInterest(journal.id, createConflictOfInterestPayload(r1.id, r2.id, { reason: 'Test reason' }), journalEditorHeaders);
            const exclusion = handleApiResponse<ConflictOfInterest>(exclusionRes, 201);

            const getRes = await apiClient.getConflictOfInterest(journal.id, exclusion.id, journalEditorHeaders);
            const retrieved = handleApiResponse<ConflictOfInterest>(getRes, 200);

            assertConflictOfInterest(retrieved);
            expect(retrieved.id).toBe(exclusion.id);
            expect(retrieved.reason).toBe('Test reason');
        });

        it('should list all conflicts of interest in ascending order of creation', async () => {
            const journal = await setupJournal();
            const r1 = await setupReviewerProfile(journal.id);
            const r2 = await setupReviewerProfile(journal.id);
            const r3 = await setupReviewerProfile(journal.id);

            const ex1Res = await apiClient.createConflictOfInterest(journal.id, createConflictOfInterestPayload(r1.id, r2.id), journalEditorHeaders);
            const ex1 = handleApiResponse<ConflictOfInterest>(ex1Res, 201);
            await new Promise(resolve => setTimeout(resolve, 10));
            const ex2Res = await apiClient.createConflictOfInterest(journal.id, createConflictOfInterestPayload(r2.id, r3.id), journalEditorHeaders);
            const ex2 = handleApiResponse<ConflictOfInterest>(ex2Res, 201);

            const listRes = await apiClient.getConflictsOfInterest(journal.id, journalEditorHeaders);
            const exclusions = handleApiResponse<ConflictOfInterest[]>(listRes, 200, { expectPaginated: true });

            expect(exclusions).toHaveLength(2);
            const exclusionIds = exclusions.map(e => e.id);
            expect(exclusionIds).toContain(ex1.id);
            expect(exclusionIds).toContain(ex2.id);
            expect(exclusions.map(e => e.id)).toEqual([ex1.id, ex2.id]);
        });
    });

    describe('Pagination on list endpoints', () => {
        it('should reject requests with out-of-bounds pagination parameters', async () => {
            const journal = await setupJournal();

            const highLimitRes = await apiClient.getReviewerProfiles(journal.id, sectionEditorHeaders, { limit: 101, offset: 0 });
            expect(highLimitRes.status).toBe(400);
            validateErrorEnvelope(highLimitRes, { expectedErrorId: ApiErrorId.ERR_INVALID_PAGINATION_PARAMETERS });

            const lowLimitRes = await apiClient.getReviewerProfiles(journal.id, sectionEditorHeaders, { limit: 0, offset: 0 });
            expect(lowLimitRes.status).toBe(400);
            validateErrorEnvelope(lowLimitRes, { expectedErrorId: ApiErrorId.ERR_INVALID_PAGINATION_PARAMETERS });

            const negativeOffsetRes = await apiClient.getReviewerProfiles(journal.id, sectionEditorHeaders, { limit: 10, offset: -1 });
            expect(negativeOffsetRes.status).toBe(400);
            validateErrorEnvelope(negativeOffsetRes, { expectedErrorId: ApiErrorId.ERR_INVALID_PAGINATION_PARAMETERS });
        });

        it('should respect limit and offset and return correct metadata for the last page', async () => {
            const journal = await setupJournal();
            await setupReviewerProfile(journal.id, { full_name: 'A' });
            await setupReviewerProfile(journal.id, { full_name: 'B' });
            const profileC = await setupReviewerProfile(journal.id, { full_name: 'C' });

            const listRes = await apiClient.getReviewerProfiles(journal.id, sectionEditorHeaders, { limit: 1, offset: 2 });

            expect(listRes.status).toBe(200);
            const envelope = validateApiResponseStructure(listRes, { expectPaginated: true });
            expect(envelope.meta.limit).toBe(1);
            expect(envelope.meta.offset).toBe(2);
            expect(envelope.meta.total_count).toBe(3);
            expect(envelope.meta.has_more).toBe(false);
            const profiles = envelope.data as ReviewerProfile[];
            expect(profiles).toHaveLength(1);
            expect(profiles[0].id).toBe(profileC.id);
        });

        it('should return has_more: true when more records exist', async () => {
            const journal = await setupJournal();
            await setupReviewerProfile(journal.id, { full_name: 'A' });
            await setupReviewerProfile(journal.id, { full_name: 'B' });
            await setupReviewerProfile(journal.id, { full_name: 'C' });

            const listRes = await apiClient.getReviewerProfiles(journal.id, sectionEditorHeaders, { limit: 2, offset: 0 });

            expect(listRes.status).toBe(200);
            const envelope = validateApiResponseStructure(listRes, { expectPaginated: true });
            expect(envelope.meta.has_more).toBe(true);
            expect(envelope.data).toHaveLength(2);
        });
    });
});
