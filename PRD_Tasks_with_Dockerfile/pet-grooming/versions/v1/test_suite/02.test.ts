import {
    apiClient,
    buildUserHeaders,
    getSuccessData,
    handleApiResponse,
    validateErrorEnvelope,
    assertGroomingDay,
    assertSessionBlock, createAndActivateGroomingDay,
    createSessionBlock,
    createGroomingJob,
    createGroomerStation,
    createJobAssignment,
    confirmJobAssignment, GroomingDay,
    SessionBlock,
    GroomingJob,
    GroomerStation,
    JobAssignment,
    GroomingDayStatus,
    SessionBlockStatus,
    GroomingJobStatus,
    JobAssignmentStatus,
    UserRole,
    ApiErrorId, generatePetId,
    createUnixTimestamp
} from '../../../test-helpers';

describe('Phase 2: State Machine Transitions (Pet Grooming)', () => {
    const clinicManagerHeaders = buildUserHeaders('manager-1', UserRole.ClinicManager);
    const technicianHeaders = buildUserHeaders('tech-1', UserRole.GroomingTechnician);
    const billingAdminHeaders = buildUserHeaders('billing-1', UserRole.BillingAdmin);

    describe('GroomingDay State Machine', () => {
        describe('Transition: activate (PLANNING -> ACTIVE)', () => {
            it('should transition grooming day from PLANNING to ACTIVE upon activation', async () => {
                const dayRes = await apiClient.createGroomingDay(
                    { schedule_name: 'Morning Pet Grooming', total_supply_budget: 1000.0 },
                    clinicManagerHeaders
                );
                const day = getSuccessData<GroomingDay>(dayRes);
                expect(day.status).toBe(GroomingDayStatus.PLANNING);

                const activateRes = await apiClient.activateGroomingDay(day.id, clinicManagerHeaders);
                const activatedDay = handleApiResponse<GroomingDay>(activateRes, 200);

                assertGroomingDay(activatedDay);
                expect(activatedDay.status).toBe(GroomingDayStatus.ACTIVE);

                const getRes = await apiClient.getGroomingDay(day.id, clinicManagerHeaders);
                const retrievedDay = handleApiResponse<GroomingDay>(getRes, 200);
                expect(retrievedDay.status).toBe(GroomingDayStatus.ACTIVE);
            });

            it('should fail with conflict error when activating an already active grooming day', async () => {
                const dayRes = await apiClient.createGroomingDay(
                    { schedule_name: 'Already Active Grooming Day', total_supply_budget: 800.0 },
                    clinicManagerHeaders
                );
                const day = getSuccessData<GroomingDay>(dayRes);

                await apiClient.activateGroomingDay(day.id, clinicManagerHeaders);

                const getRes = await apiClient.getGroomingDay(day.id, clinicManagerHeaders);
                const activeDay = handleApiResponse<GroomingDay>(getRes, 200);
                expect(activeDay.status).toBe(GroomingDayStatus.ACTIVE);

                const secondActivateRes = await apiClient.activateGroomingDay(day.id, clinicManagerHeaders);

                validateErrorEnvelope(secondActivateRes, {
                    expectedErrorId: ApiErrorId.ERR_DAY_NOT_IN_PLANNING
                });

                const finalGetRes = await apiClient.getGroomingDay(day.id, clinicManagerHeaders);
                const finalDay = handleApiResponse<GroomingDay>(finalGetRes, 200);
                expect(finalDay.status).toBe(GroomingDayStatus.ACTIVE);
            });

            it('should fail with conflict error when activating a day in INVOICING_PENDING state', async () => {
                const dayRes = await apiClient.createGroomingDay(
                    { schedule_name: 'Invoicing Pending Day', total_supply_budget: 600.0 },
                    clinicManagerHeaders
                );
                const day = getSuccessData<GroomingDay>(dayRes);

                await apiClient.activateGroomingDay(day.id, clinicManagerHeaders);
                await apiClient.initiateInvoicing(day.id, clinicManagerHeaders);

                const getRes = await apiClient.getGroomingDay(day.id, clinicManagerHeaders);
                const invoicingPendingDay = handleApiResponse<GroomingDay>(getRes, 200);
                expect(invoicingPendingDay.status).toBe(GroomingDayStatus.INVOICING_PENDING);

                const activateRes = await apiClient.activateGroomingDay(day.id, clinicManagerHeaders);

                validateErrorEnvelope(activateRes, {
                    expectedErrorId: ApiErrorId.ERR_DAY_NOT_IN_PLANNING
                });

                const finalGetRes = await apiClient.getGroomingDay(day.id, clinicManagerHeaders);
                const finalDay = handleApiResponse<GroomingDay>(finalGetRes, 200);
                expect(finalDay.status).toBe(GroomingDayStatus.INVOICING_PENDING);
            });
        });

        describe('Transition: initiate_invoicing (ACTIVE -> INVOICING_PENDING)', () => {
            it('should transition grooming day from ACTIVE to INVOICING_PENDING when invoicing is initiated', async () => {
                const dayRes = await apiClient.createGroomingDay(
                    { schedule_name: 'Invoicing Test Day', total_supply_budget: 1200.0 },
                    clinicManagerHeaders
                );
                const day = getSuccessData<GroomingDay>(dayRes);

                const activateRes = await apiClient.activateGroomingDay(day.id, clinicManagerHeaders);
                const activeDay = handleApiResponse<GroomingDay>(activateRes, 200);
                expect(activeDay.status).toBe(GroomingDayStatus.ACTIVE);

                const invoicingRes = await apiClient.initiateInvoicing(day.id, clinicManagerHeaders);
                const invoicingPendingDay = handleApiResponse<GroomingDay>(invoicingRes, 200);

                assertGroomingDay(invoicingPendingDay);
                expect(invoicingPendingDay.status).toBe(GroomingDayStatus.INVOICING_PENDING);

                const getRes = await apiClient.getGroomingDay(day.id, clinicManagerHeaders);
                const retrievedDay = handleApiResponse<GroomingDay>(getRes, 200);
                expect(retrievedDay.status).toBe(GroomingDayStatus.INVOICING_PENDING);
            });

            it('should fail with conflict error when initiating invoicing for a day in PLANNING state', async () => {
                const dayRes = await apiClient.createGroomingDay(
                    { schedule_name: 'Planning Day', total_supply_budget: 500.0 },
                    clinicManagerHeaders
                );
                const day = getSuccessData<GroomingDay>(dayRes);
                expect(day.status).toBe(GroomingDayStatus.PLANNING);

                const invoicingRes = await apiClient.initiateInvoicing(day.id, clinicManagerHeaders);

                validateErrorEnvelope(invoicingRes, {
                    expectedErrorId: ApiErrorId.ERR_DAY_NOT_ACTIVE
                });

                const getRes = await apiClient.getGroomingDay(day.id, clinicManagerHeaders);
                const finalDay = handleApiResponse<GroomingDay>(getRes, 200);
                expect(finalDay.status).toBe(GroomingDayStatus.PLANNING);
            });
        });

        describe('Transition: generate_invoice_report (INVOICING_PENDING -> CLOSED)', () => {
            it('should transition grooming day from INVOICING_PENDING to CLOSED when invoice report is generated', async () => {
                const dayRes = await apiClient.createGroomingDay(
                    { schedule_name: 'Generate Invoice Day', total_supply_budget: 1000.0 },
                    clinicManagerHeaders
                );
                const day = getSuccessData<GroomingDay>(dayRes);

                await apiClient.activateGroomingDay(day.id, clinicManagerHeaders);

                const invoicingRes = await apiClient.initiateInvoicing(day.id, clinicManagerHeaders);
                const invoicingPendingDay = handleApiResponse<GroomingDay>(invoicingRes, 200);
                expect(invoicingPendingDay.status).toBe(GroomingDayStatus.INVOICING_PENDING);

                const generateReportRes = await apiClient.generateInvoiceReport(day.id, billingAdminHeaders);
                const closedDay = handleApiResponse<GroomingDay>(generateReportRes, 200);

                assertGroomingDay(closedDay);
                expect(closedDay.status).toBe(GroomingDayStatus.CLOSED);

                const getRes = await apiClient.getGroomingDay(day.id, clinicManagerHeaders);
                const retrievedDay = handleApiResponse<GroomingDay>(getRes, 200);
                expect(retrievedDay.status).toBe(GroomingDayStatus.CLOSED);
            });

            it('should fail with conflict error when generating invoice report for a day still in ACTIVE state', async () => {
                const dayRes = await apiClient.createGroomingDay(
                    { schedule_name: 'Active Day', total_supply_budget: 750.0 },
                    clinicManagerHeaders
                );
                const day = getSuccessData<GroomingDay>(dayRes);

                const activateRes = await apiClient.activateGroomingDay(day.id, clinicManagerHeaders);
                const activeDay = handleApiResponse<GroomingDay>(activateRes, 200);
                expect(activeDay.status).toBe(GroomingDayStatus.ACTIVE);

                const generateReportRes = await apiClient.generateInvoiceReport(day.id, billingAdminHeaders);

                validateErrorEnvelope(generateReportRes, {
                    expectedErrorId: ApiErrorId.ERR_DAY_NOT_READY_FOR_INVOICING
                });

                const getRes = await apiClient.getGroomingDay(day.id, clinicManagerHeaders);
                const finalDay = handleApiResponse<GroomingDay>(getRes, 200);
                expect(finalDay.status).toBe(GroomingDayStatus.ACTIVE);
            });
        });
    });

    describe('SessionBlock State Machine', () => {
        let testDay: GroomingDay;

        beforeEach(async () => {
            testDay = await createAndActivateGroomingDay('Block Test Day', 1500.0, 'manager-1');
        });

        describe('Transition: mark_ready_for_grooming (PLANNING -> READY_FOR_GROOMING)', () => {
            it('should transition session block from PLANNING to READY_FOR_GROOMING when all jobs are confirmed', async () => {
                const block = await createSessionBlock(testDay.id, 'Morning Appointments', 2, 4);

                const job = await createGroomingJob(
                    testDay.id,
                    block.id,
                    generatePetId(1),
                    'Full Grooming',
                    2,
                    60
                );

                const station = await createGroomerStation(
                    testDay.id,
                    'Station 1',
                    'Standard',
                    25.0
                );

                const assignment = await createJobAssignment(testDay.id, job.id, station.id);
                await confirmJobAssignment(testDay.id, assignment.id);

                const confirmedJobRes = await apiClient.getGroomingJob(testDay.id, block.id, job.id, clinicManagerHeaders);
                const confirmedJob = handleApiResponse<GroomingJob>(confirmedJobRes, 200);
                expect(confirmedJob.status).toBe(GroomingJobStatus.CONFIRMED);

                const updateRes = await apiClient.updateSessionBlockStatus(
                    testDay.id,
                    block.id,
                    { status: SessionBlockStatus.READY_FOR_GROOMING },
                    clinicManagerHeaders
                );
                const readyBlock = handleApiResponse<SessionBlock>(updateRes, 200);

                assertSessionBlock(readyBlock);
                expect(readyBlock.status).toBe(SessionBlockStatus.READY_FOR_GROOMING);

                const getRes = await apiClient.getSessionBlock(testDay.id, block.id, clinicManagerHeaders);
                const retrievedBlock = handleApiResponse<SessionBlock>(getRes, 200);
                expect(retrievedBlock.status).toBe(SessionBlockStatus.READY_FOR_GROOMING);
            });

            it('should fail with conflict error when marking a cancelled block as ready', async () => {
                const blockRes = await apiClient.createSessionBlock(
                    testDay.id,
                    { name: 'Cancelled Block', start_time: createUnixTimestamp(1), end_time: createUnixTimestamp(3) },
                    technicianHeaders
                );
                const block = getSuccessData<SessionBlock>(blockRes);

                const cancelRes = await apiClient.updateSessionBlockStatus(
                    testDay.id,
                    block.id,
                    { status: SessionBlockStatus.CANCELLED },
                    clinicManagerHeaders
                );
                const cancelledBlock = handleApiResponse<SessionBlock>(cancelRes, 200);
                expect(cancelledBlock.status).toBe(SessionBlockStatus.CANCELLED);

                const updateRes = await apiClient.updateSessionBlockStatus(
                    testDay.id,
                    block.id,
                    { status: SessionBlockStatus.READY_FOR_GROOMING },
                    clinicManagerHeaders
                );

                validateErrorEnvelope(updateRes, {
                    expectedErrorId: ApiErrorId.ERR_ILLEGAL_BLOCK_STATE_TRANSITION
                });

                const getRes = await apiClient.getSessionBlock(testDay.id, block.id, clinicManagerHeaders);
                const finalBlock = handleApiResponse<SessionBlock>(getRes, 200);
                expect(finalBlock.status).toBe(SessionBlockStatus.CANCELLED);
            });
        });

        describe('Transition: cancel (PLANNING -> CANCELLED)', () => {
            it('should transition session block from PLANNING to CANCELLED', async () => {
                const blockRes = await apiClient.createSessionBlock(
                    testDay.id,
                    { name: 'To Cancel Block', start_time: createUnixTimestamp(1), end_time: createUnixTimestamp(3) },
                    technicianHeaders
                );
                const block = getSuccessData<SessionBlock>(blockRes);
                expect(block.status).toBe(SessionBlockStatus.PLANNING);

                const updateRes = await apiClient.updateSessionBlockStatus(
                    testDay.id,
                    block.id,
                    { status: SessionBlockStatus.CANCELLED },
                    clinicManagerHeaders
                );
                const cancelledBlock = handleApiResponse<SessionBlock>(updateRes, 200);

                assertSessionBlock(cancelledBlock);
                expect(cancelledBlock.status).toBe(SessionBlockStatus.CANCELLED);

                const getRes = await apiClient.getSessionBlock(testDay.id, block.id, clinicManagerHeaders);
                const retrievedBlock = handleApiResponse<SessionBlock>(getRes, 200);
                expect(retrievedBlock.status).toBe(SessionBlockStatus.CANCELLED);
            });

            it('should fail with conflict error when cancelling an already cancelled block', async () => {
                const blockRes = await apiClient.createSessionBlock(
                    testDay.id,
                    { name: 'Already Cancelled Block', start_time: createUnixTimestamp(1), end_time: createUnixTimestamp(3) },
                    technicianHeaders
                );
                const block = getSuccessData<SessionBlock>(blockRes);

                await apiClient.updateSessionBlockStatus(
                    testDay.id,
                    block.id,
                    { status: SessionBlockStatus.CANCELLED },
                    clinicManagerHeaders
                );

                const getRes = await apiClient.getSessionBlock(testDay.id, block.id, clinicManagerHeaders);
                const cancelledBlock = handleApiResponse<SessionBlock>(getRes, 200);
                expect(cancelledBlock.status).toBe(SessionBlockStatus.CANCELLED);

                const secondCancelRes = await apiClient.updateSessionBlockStatus(
                    testDay.id,
                    block.id,
                    { status: SessionBlockStatus.CANCELLED },
                    clinicManagerHeaders
                );

                validateErrorEnvelope(secondCancelRes, {
                    expectedErrorId: ApiErrorId.ERR_ILLEGAL_BLOCK_STATE_TRANSITION
                });

                const finalGetRes = await apiClient.getSessionBlock(testDay.id, block.id, clinicManagerHeaders);
                const finalBlock = handleApiResponse<SessionBlock>(finalGetRes, 200);
                expect(finalBlock.status).toBe(SessionBlockStatus.CANCELLED);
            });
        });

        describe('Transition: cancel (READY_FOR_GROOMING -> CANCELLED)', () => {
            it('should transition session block from READY_FOR_GROOMING to CANCELLED', async () => {
                const block = await createSessionBlock(testDay.id, 'Ready Block', 2, 4);

                const job = await createGroomingJob(
                    testDay.id,
                    block.id,
                    generatePetId(1),
                    'Basic Grooming',
                    2,
                    45
                );

                const station = await createGroomerStation(
                    testDay.id,
                    'Station 1',
                    'Standard',
                    20.0
                );

                const assignment = await createJobAssignment(testDay.id, job.id, station.id);
                await confirmJobAssignment(testDay.id, assignment.id);

                const readyRes = await apiClient.updateSessionBlockStatus(
                    testDay.id,
                    block.id,
                    { status: SessionBlockStatus.READY_FOR_GROOMING },
                    clinicManagerHeaders
                );
                const readyBlock = handleApiResponse<SessionBlock>(readyRes, 200);
                expect(readyBlock.status).toBe(SessionBlockStatus.READY_FOR_GROOMING);

                const cancelRes = await apiClient.updateSessionBlockStatus(
                    testDay.id,
                    block.id,
                    { status: SessionBlockStatus.CANCELLED },
                    clinicManagerHeaders
                );
                const cancelledBlock = handleApiResponse<SessionBlock>(cancelRes, 200);

                assertSessionBlock(cancelledBlock);
                expect(cancelledBlock.status).toBe(SessionBlockStatus.CANCELLED);

                const getRes = await apiClient.getSessionBlock(testDay.id, block.id, clinicManagerHeaders);
                const retrievedBlock = handleApiResponse<SessionBlock>(getRes, 200);
                expect(retrievedBlock.status).toBe(SessionBlockStatus.CANCELLED);
            });
        });

        describe('Transition: downgrade_to_planning (READY_FOR_GROOMING -> PLANNING)', () => {
            it('should transition session block from READY_FOR_GROOMING to PLANNING when an assignment is terminated', async () => {
                const block = await createSessionBlock(testDay.id, 'Downgrade Block', 2, 4);

                const job = await createGroomingJob(
                    testDay.id,
                    block.id,
                    generatePetId(1),
                    'Premium Grooming',
                    2,
                    90
                );

                const station = await createGroomerStation(
                    testDay.id,
                    'Station 1',
                    'Premium',
                    30.0
                );

                const assignment = await createJobAssignment(testDay.id, job.id, station.id);
                const confirmedAssignment = await confirmJobAssignment(testDay.id, assignment.id);

                const readyRes = await apiClient.updateSessionBlockStatus(
                    testDay.id,
                    block.id,
                    { status: SessionBlockStatus.READY_FOR_GROOMING },
                    clinicManagerHeaders
                );
                const readyBlock = handleApiResponse<SessionBlock>(readyRes, 200);
                expect(readyBlock.status).toBe(SessionBlockStatus.READY_FOR_GROOMING);

                const terminateRes = await apiClient.terminateJobAssignment(
                    testDay.id,
                    confirmedAssignment.id,
                    clinicManagerHeaders
                );
                expect(terminateRes.status).toBe(200);

                const getRes = await apiClient.getSessionBlock(testDay.id, block.id, clinicManagerHeaders);
                const downgradedBlock = handleApiResponse<SessionBlock>(getRes, 200);
                expect(downgradedBlock.status).toBe(SessionBlockStatus.PLANNING);
            });

            it('should keep session block in PLANNING state when an assignment is terminated', async () => {
                const block = await createSessionBlock(testDay.id, 'Stay Planning Block', 2, 4);

                const job = await createGroomingJob(
                    testDay.id,
                    block.id,
                    generatePetId(1),
                    'Basic Grooming',
                    2,
                    60
                );

                const station = await createGroomerStation(
                    testDay.id,
                    'Station 1',
                    'Standard',
                    25.0
                );

                const assignment = await createJobAssignment(testDay.id, job.id, station.id);
                const confirmedAssignment = await confirmJobAssignment(testDay.id, assignment.id);

                const blockBeforeTerminateRes = await apiClient.getSessionBlock(testDay.id, block.id, clinicManagerHeaders);
                const blockBeforeTerminate = handleApiResponse<SessionBlock>(blockBeforeTerminateRes, 200);
                expect(blockBeforeTerminate.status).toBe(SessionBlockStatus.PLANNING);

                const terminateRes = await apiClient.terminateJobAssignment(
                    testDay.id,
                    confirmedAssignment.id,
                    clinicManagerHeaders
                );
                expect(terminateRes.status).toBe(200);

                const getRes = await apiClient.getSessionBlock(testDay.id, block.id, clinicManagerHeaders);
                const blockAfterTerminate = handleApiResponse<SessionBlock>(getRes, 200);
                expect(blockAfterTerminate.status).toBe(SessionBlockStatus.PLANNING);
            });
        });
    });

    describe('GroomingJob State Machine', () => {
        let testDay: GroomingDay;
        let testBlock: SessionBlock;

        beforeEach(async () => {
            testDay = await createAndActivateGroomingDay('Job Test Day', 2000.0, 'manager-1');
            testBlock = await createSessionBlock(testDay.id, 'Job Test Block', 2, 4);
        });

        describe('Transition: propose_assignment (PENDING -> SCHEDULED)', () => {
            it('should transition grooming job from PENDING to SCHEDULED when assignment is proposed', async () => {
                const jobRes = await apiClient.createGroomingJob(
                    testDay.id,
                    testBlock.id,
                    {
                        pet_id: generatePetId(1),
                        job_type: 'Full Service Grooming',
                        start_time: createUnixTimestamp(2),
                        end_time: createUnixTimestamp(2) + 3600,
                    },
                    technicianHeaders
                );
                const job = getSuccessData<GroomingJob>(jobRes);
                expect(job.status).toBe(GroomingJobStatus.PENDING);

                const stationRes = await apiClient.createGroomerStation(
                    testDay.id,
                    { station_name: 'Grooming Station 1', station_type: 'Standard', supply_cost_per_hour: 25.0 },
                    technicianHeaders
                );
                const station = getSuccessData<GroomerStation>(stationRes);

                const assignmentRes = await apiClient.createJobAssignment(
                    testDay.id,
                    { job_id: job.id, station_id: station.id },
                    technicianHeaders
                );
                expect(assignmentRes.status).toBe(201);

                const getJobRes = await apiClient.getGroomingJob(
                    testDay.id,
                    testBlock.id,
                    job.id,
                    clinicManagerHeaders
                );
                const updatedJob = handleApiResponse<GroomingJob>(getJobRes, 200);
                expect(updatedJob.status).toBe(GroomingJobStatus.SCHEDULED);
            });

            it('should fail with conflict error when proposing assignment to a confirmed job', async () => {
                const job = await createGroomingJob(
                    testDay.id,
                    testBlock.id,
                    generatePetId(1),
                    'Premium Grooming',
                    2,
                    90
                );

                const station1 = await createGroomerStation(
                    testDay.id,
                    'Station 1',
                    'Premium',
                    35.0
                );

                const assignment1 = await createJobAssignment(testDay.id, job.id, station1.id);
                await confirmJobAssignment(testDay.id, assignment1.id);

                const station2Res = await apiClient.createGroomerStation(
                    testDay.id,
                    { station_name: 'Station 2', station_type: 'Premium', supply_cost_per_hour: 40.0 },
                    technicianHeaders
                );
                const station2 = getSuccessData<GroomerStation>(station2Res);

                const confirmedJobRes = await apiClient.getGroomingJob(
                    testDay.id,
                    testBlock.id,
                    job.id,
                    clinicManagerHeaders
                );
                const confirmedJob = handleApiResponse<GroomingJob>(confirmedJobRes, 200);
                expect(confirmedJob.status).toBe(GroomingJobStatus.CONFIRMED);

                const assignment2Res = await apiClient.createJobAssignment(
                    testDay.id,
                    { job_id: job.id, station_id: station2.id },
                    technicianHeaders
                );

                validateErrorEnvelope(assignment2Res, {
                    expectedErrorId: ApiErrorId.ERR_JOB_NOT_PENDING
                });

                const finalJobRes = await apiClient.getGroomingJob(
                    testDay.id,
                    testBlock.id,
                    job.id,
                    clinicManagerHeaders
                );
                const finalJob = handleApiResponse<GroomingJob>(finalJobRes, 200);
                expect(finalJob.status).toBe(GroomingJobStatus.CONFIRMED);
            });
        });

        describe('Transition: reopen_job (SCHEDULED -> PENDING)', () => {
            it('should transition grooming job from SCHEDULED to PENDING when assignment is terminated', async () => {
                const jobRes = await apiClient.createGroomingJob(
                    testDay.id,
                    testBlock.id,
                    {
                        pet_id: generatePetId(2),
                        job_type: 'Nail Trimming',
                        start_time: createUnixTimestamp(2),
                        end_time: createUnixTimestamp(2) + 1800,
                    },
                    technicianHeaders
                );
                const job = getSuccessData<GroomingJob>(jobRes);

                const stationRes = await apiClient.createGroomerStation(
                    testDay.id,
                    { station_name: 'Quick Service Station', station_type: 'Express', supply_cost_per_hour: 15.0 },
                    technicianHeaders
                );
                const station = getSuccessData<GroomerStation>(stationRes);

                const assignmentRes = await apiClient.createJobAssignment(
                    testDay.id,
                    { job_id: job.id, station_id: station.id },
                    technicianHeaders
                );
                const assignment = getSuccessData<JobAssignment>(assignmentRes);

                const scheduledJobRes = await apiClient.getGroomingJob(
                    testDay.id,
                    testBlock.id,
                    job.id,
                    clinicManagerHeaders
                );
                const scheduledJob = handleApiResponse<GroomingJob>(scheduledJobRes, 200);
                expect(scheduledJob.status).toBe(GroomingJobStatus.SCHEDULED);

                const terminateRes = await apiClient.terminateJobAssignment(
                    testDay.id,
                    assignment.id,
                    clinicManagerHeaders
                );
                expect(terminateRes.status).toBe(200);

                const getJobRes = await apiClient.getGroomingJob(
                    testDay.id,
                    testBlock.id,
                    job.id,
                    clinicManagerHeaders
                );
                const reopenedJob = handleApiResponse<GroomingJob>(getJobRes, 200);
                expect(reopenedJob.status).toBe(GroomingJobStatus.PENDING);
            });

            it('should return error when terminating non-existent assignment', async () => {
                const jobRes = await apiClient.createGroomingJob(
                    testDay.id,
                    testBlock.id,
                    {
                        pet_id: generatePetId(3),
                        job_type: 'Bath Only',
                        start_time: createUnixTimestamp(2),
                        end_time: createUnixTimestamp(2) + 2700,
                    },
                    technicianHeaders
                );
                const job = getSuccessData<GroomingJob>(jobRes);
                expect(job.status).toBe(GroomingJobStatus.PENDING);

                const NON_EXISTENT_UUID = '00000000-0000-0000-0000-000000000000';
                const terminateRes = await apiClient.terminateJobAssignment(
                    testDay.id,
                    NON_EXISTENT_UUID,
                    clinicManagerHeaders
                );

                validateErrorEnvelope(terminateRes, {
                    expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND
                });

                const getJobRes = await apiClient.getGroomingJob(
                    testDay.id,
                    testBlock.id,
                    job.id,
                    clinicManagerHeaders
                );
                const unchangedJob = handleApiResponse<GroomingJob>(getJobRes, 200);
                expect(unchangedJob.status).toBe(GroomingJobStatus.PENDING);
            });
        });

        describe('Transition: reopen_job (CONFIRMED -> PENDING)', () => {
            it('should transition grooming job from CONFIRMED to PENDING when confirmed assignment is terminated', async () => {
                const job = await createGroomingJob(
                    testDay.id,
                    testBlock.id,
                    generatePetId(4),
                    'Deluxe Grooming',
                    2,
                    120
                );

                const station = await createGroomerStation(
                    testDay.id,
                    'Deluxe Station',
                    'Deluxe',
                    50.0
                );

                const assignment = await createJobAssignment(testDay.id, job.id, station.id);
                const confirmedAssignment = await confirmJobAssignment(testDay.id, assignment.id);

                const confirmedJobRes = await apiClient.getGroomingJob(
                    testDay.id,
                    testBlock.id,
                    job.id,
                    clinicManagerHeaders
                );
                const confirmedJob = handleApiResponse<GroomingJob>(confirmedJobRes, 200);
                expect(confirmedJob.status).toBe(GroomingJobStatus.CONFIRMED);

                const terminateRes = await apiClient.terminateJobAssignment(
                    testDay.id,
                    confirmedAssignment.id,
                    clinicManagerHeaders
                );
                expect(terminateRes.status).toBe(200);

                const getJobRes = await apiClient.getGroomingJob(
                    testDay.id,
                    testBlock.id,
                    job.id,
                    clinicManagerHeaders
                );
                const reopenedJob = handleApiResponse<GroomingJob>(getJobRes, 200);
                expect(reopenedJob.status).toBe(GroomingJobStatus.PENDING);
            });

            it('should not reopen cancelled job when trying to terminate already-terminated assignment', async () => {
                const job = await createGroomingJob(
                    testDay.id,
                    testBlock.id,
                    generatePetId(5),
                    'Standard Grooming',
                    2,
                    75
                );

                const station = await createGroomerStation(
                    testDay.id,
                    'Standard Station',
                    'Standard',
                    30.0
                );

                const assignment = await createJobAssignment(testDay.id, job.id, station.id);
                const confirmedAssignment = await confirmJobAssignment(testDay.id, assignment.id);

                await apiClient.updateSessionBlockStatus(
                    testDay.id,
                    testBlock.id,
                    { status: SessionBlockStatus.CANCELLED },
                    clinicManagerHeaders
                );

                const cancelledJobRes = await apiClient.getGroomingJob(
                    testDay.id,
                    testBlock.id,
                    job.id,
                    clinicManagerHeaders
                );
                const cancelledJob = handleApiResponse<GroomingJob>(cancelledJobRes, 200);
                expect(cancelledJob.status).toBe(GroomingJobStatus.CANCELLED);

                const terminateRes = await apiClient.terminateJobAssignment(
                    testDay.id,
                    confirmedAssignment.id,
                    clinicManagerHeaders
                );

                validateErrorEnvelope(terminateRes, {
                    expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_TERMINABLE
                });

                const finalJobRes = await apiClient.getGroomingJob(
                    testDay.id,
                    testBlock.id,
                    job.id,
                    clinicManagerHeaders
                );
                const finalJob = handleApiResponse<GroomingJob>(finalJobRes, 200);
                expect(finalJob.status).toBe(GroomingJobStatus.CANCELLED);
            });
        });

        describe('Transition: confirm_assignment (SCHEDULED -> CONFIRMED)', () => {
            it('should transition grooming job from SCHEDULED to CONFIRMED when assignment is confirmed', async () => {
                const jobRes = await apiClient.createGroomingJob(
                    testDay.id,
                    testBlock.id,
                    {
                        pet_id: generatePetId(6),
                        job_type: 'Specialty Grooming',
                        start_time: createUnixTimestamp(2),
                        end_time: createUnixTimestamp(2) + 5400,
                    },
                    technicianHeaders
                );
                const job = getSuccessData<GroomingJob>(jobRes);

                const stationRes = await apiClient.createGroomerStation(
                    testDay.id,
                    { station_name: 'Specialty Station', station_type: 'Specialty', supply_cost_per_hour: 45.0 },
                    technicianHeaders
                );
                const station = getSuccessData<GroomerStation>(stationRes);

                const assignmentRes = await apiClient.createJobAssignment(
                    testDay.id,
                    { job_id: job.id, station_id: station.id },
                    technicianHeaders
                );
                const assignment = getSuccessData<JobAssignment>(assignmentRes);

                const scheduledJobRes = await apiClient.getGroomingJob(
                    testDay.id,
                    testBlock.id,
                    job.id,
                    clinicManagerHeaders
                );
                const scheduledJob = handleApiResponse<GroomingJob>(scheduledJobRes, 200);
                expect(scheduledJob.status).toBe(GroomingJobStatus.SCHEDULED);

                const confirmRes = await apiClient.confirmJobAssignment(
                    testDay.id,
                    assignment.id,
                    clinicManagerHeaders
                );
                expect(confirmRes.status).toBe(200);

                const getJobRes = await apiClient.getGroomingJob(
                    testDay.id,
                    testBlock.id,
                    job.id,
                    clinicManagerHeaders
                );
                const confirmedJob = handleApiResponse<GroomingJob>(getJobRes, 200);
                expect(confirmedJob.status).toBe(GroomingJobStatus.CONFIRMED);
            });

            it('should fail when trying to confirm a terminated assignment', async () => {
                const jobRes = await apiClient.createGroomingJob(
                    testDay.id,
                    testBlock.id,
                    {
                        pet_id: generatePetId(7),
                        job_type: 'Basic Wash',
                        start_time: createUnixTimestamp(2),
                        end_time: createUnixTimestamp(2) + 1800,
                    },
                    technicianHeaders
                );
                const job = getSuccessData<GroomingJob>(jobRes);

                const stationRes = await apiClient.createGroomerStation(
                    testDay.id,
                    { station_name: 'Wash Station', station_type: 'Basic', supply_cost_per_hour: 20.0 },
                    technicianHeaders
                );
                const station = getSuccessData<GroomerStation>(stationRes);

                const assignmentRes = await apiClient.createJobAssignment(
                    testDay.id,
                    { job_id: job.id, station_id: station.id },
                    technicianHeaders
                );
                const assignment = getSuccessData<JobAssignment>(assignmentRes);

                await apiClient.terminateJobAssignment(testDay.id, assignment.id, clinicManagerHeaders);

                const pendingJobRes = await apiClient.getGroomingJob(
                    testDay.id,
                    testBlock.id,
                    job.id,
                    clinicManagerHeaders
                );
                const pendingJob = handleApiResponse<GroomingJob>(pendingJobRes, 200);
                expect(pendingJob.status).toBe(GroomingJobStatus.PENDING);

                const confirmRes = await apiClient.confirmJobAssignment(
                    testDay.id,
                    assignment.id,
                    clinicManagerHeaders
                );

                validateErrorEnvelope(confirmRes, {
                    expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_PROPOSED
                });

                const finalJobRes = await apiClient.getGroomingJob(
                    testDay.id,
                    testBlock.id,
                    job.id,
                    clinicManagerHeaders
                );
                const finalJob = handleApiResponse<GroomingJob>(finalJobRes, 200);
                expect(finalJob.status).toBe(GroomingJobStatus.PENDING);
            });
        });

        describe('Transition: cancel (PENDING/SCHEDULED/CONFIRMED -> CANCELLED)', () => {
            it('should transition grooming job from SCHEDULED to CANCELLED when parent session block is cancelled', async () => {
                const jobRes = await apiClient.createGroomingJob(
                    testDay.id,
                    testBlock.id,
                    {
                        pet_id: generatePetId(8),
                        job_type: 'Monitoring Grooming',
                        start_time: createUnixTimestamp(2),
                        end_time: createUnixTimestamp(2) + 3600,
                    },
                    technicianHeaders
                );
                const job = getSuccessData<GroomingJob>(jobRes);

                const stationRes = await apiClient.createGroomerStation(
                    testDay.id,
                    { station_name: 'Monitor Station', station_type: 'Monitoring', supply_cost_per_hour: 35.0 },
                    technicianHeaders
                );
                const station = getSuccessData<GroomerStation>(stationRes);

                const assignmentRes = await apiClient.createJobAssignment(
                    testDay.id,
                    { job_id: job.id, station_id: station.id },
                    technicianHeaders
                );
                const assignment = getSuccessData<JobAssignment>(assignmentRes);

                const scheduledJobRes = await apiClient.getGroomingJob(
                    testDay.id,
                    testBlock.id,
                    job.id,
                    clinicManagerHeaders
                );
                const scheduledJob = handleApiResponse<GroomingJob>(scheduledJobRes, 200);
                expect(scheduledJob.status).toBe(GroomingJobStatus.SCHEDULED);

                const cancelRes = await apiClient.updateSessionBlockStatus(
                    testDay.id,
                    testBlock.id,
                    { status: SessionBlockStatus.CANCELLED },
                    clinicManagerHeaders
                );
                expect(cancelRes.status).toBe(200);

                const getJobRes = await apiClient.getGroomingJob(
                    testDay.id,
                    testBlock.id,
                    job.id,
                    clinicManagerHeaders
                );
                const cancelledJob = handleApiResponse<GroomingJob>(getJobRes, 200);
                expect(cancelledJob.status).toBe(GroomingJobStatus.CANCELLED);

                const getAssignmentRes = await apiClient.getJobAssignment(testDay.id, assignment.id, clinicManagerHeaders);
                const terminatedAssignment = handleApiResponse<JobAssignment>(getAssignmentRes, 200);
                expect(terminatedAssignment.status).toBe(JobAssignmentStatus.TERMINATED);
            });

            it('should remain CANCELLED when parent session block is cancelled again', async () => {
                const jobRes = await apiClient.createGroomingJob(
                    testDay.id,
                    testBlock.id,
                    {
                        pet_id: generatePetId(9),
                        job_type: 'Backup Grooming',
                        start_time: createUnixTimestamp(2),
                        end_time: createUnixTimestamp(2) + 2700,
                    },
                    technicianHeaders
                );
                const job = getSuccessData<GroomingJob>(jobRes);

                await apiClient.updateSessionBlockStatus(
                    testDay.id,
                    testBlock.id,
                    { status: SessionBlockStatus.CANCELLED },
                    clinicManagerHeaders
                );

                const cancelledJobRes = await apiClient.getGroomingJob(
                    testDay.id,
                    testBlock.id,
                    job.id,
                    clinicManagerHeaders
                );
                const cancelledJob = handleApiResponse<GroomingJob>(cancelledJobRes, 200);
                expect(cancelledJob.status).toBe(GroomingJobStatus.CANCELLED);

                const secondCancelRes = await apiClient.updateSessionBlockStatus(
                    testDay.id,
                    testBlock.id,
                    { status: SessionBlockStatus.CANCELLED },
                    clinicManagerHeaders
                );

                validateErrorEnvelope(secondCancelRes, {
                    expectedErrorId: ApiErrorId.ERR_ILLEGAL_BLOCK_STATE_TRANSITION
                });

                const finalJobRes = await apiClient.getGroomingJob(
                    testDay.id,
                    testBlock.id,
                    job.id,
                    clinicManagerHeaders
                );
                const finalJob = handleApiResponse<GroomingJob>(finalJobRes, 200);
                expect(finalJob.status).toBe(GroomingJobStatus.CANCELLED);
            });
        });
    });
});
