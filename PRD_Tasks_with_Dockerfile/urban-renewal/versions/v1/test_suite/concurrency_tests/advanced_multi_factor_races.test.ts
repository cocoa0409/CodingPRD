import { v4 as uuidv4 } from 'uuid';
import {
  apiClient,
  buildAuthHeaders,
  createContractPayload,
  createCrewPayload,
  createPhasePayload,
  createProjectPayload,
  createWorkOrderPayload,
  getSuccessData,
  CrewContract,
  RenovationPhase,
  RenovationCrew,
  UrbanRenewalProject,
  WorkOrder,
} from '../../../../test-helpers';
import { validateErrorEnvelope } from '../../../../test-helpers/validators';
import { ApiErrorId } from '../../../../test-helpers/api-errors';

describe('Concurrency — Advanced Multi-Factor & Schedule Timing Races', () => {
  it('schedule atomicity vs multiple cost factors: hazard + disruption + budget', async () => {
    const headers = buildAuthHeaders('schedule-multi-factor');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({
          project_name: 'Multi Factor Schedule',
          renovation_budget: 60_000
        }),
        headers
      )
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(
        project.id,
        createPhasePayload({ name: 'Multi Factor Phase', start_hour: 0, end_hour: 300 }),
        headers
      )
    );

    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'Multi Factor Crew', hourly_rate: 100 }),
        headers
      )
    );

    for (let i = 0; i < 3; i++) {
      const setupOrder = getSuccessData<WorkOrder>(
        await apiClient.createWorkOrder(
          project.id,
          phase.id,
          createWorkOrderPayload({
            task_type: `Setup ${i}`,
            start_hour: i * 100,
            end_hour: i * 100 + 80
          }),
          headers
        )
      );
      const setupContract = getSuccessData<CrewContract>(
        await apiClient.createContract(
          project.id,
          createContractPayload(setupOrder.id, crew.id),
          headers
        )
      );
      getSuccessData(await apiClient.verifySpecialization(project.id, setupContract.id, headers));
      getSuccessData(await apiClient.scheduleWork(project.id, setupContract.id, headers));
    }

    const crew2 = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'Boundary Crew', hourly_rate: 100 }),
        headers
      )
    );

    const seedOrder = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'Seed Work',
          start_hour: 0,
          end_hour: 159
        }),
        headers
      )
    );
    const seedContract = getSuccessData<CrewContract>(
      await apiClient.createContract(
        project.id,
        createContractPayload(seedOrder.id, crew2.id),
        headers
      )
    );
    getSuccessData(await apiClient.verifySpecialization(project.id, seedContract.id, headers));
    getSuccessData(await apiClient.scheduleWork(project.id, seedContract.id, headers));

    const orderK = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'Critical Task',
          start_hour: 270,
          end_hour: 272
        }),
        headers
      )
    );
    const contractK = getSuccessData<CrewContract>(
      await apiClient.createContract(
        project.id,
        createContractPayload(orderK.id, crew2.id),
        headers
      )
    );
    getSuccessData(await apiClient.verifySpecialization(project.id, contractK.id, headers));

    const consumeOrder = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'Consume Budget',
          start_hour: 280,
          end_hour: 300
        }),
        headers
      )
    );

    const projectBefore = getSuccessData<UrbanRenewalProject>(
      await apiClient.getProject(project.id, headers)
    );

    const [scheduleRes, consumeRes] = await Promise.all([
      apiClient.scheduleWork(project.id, contractK.id, headers),
      apiClient.createContract(project.id, createContractPayload(consumeOrder.id, crew.id), headers),
    ]);

    if (scheduleRes.status === 200) {
      const finalK = getSuccessData<CrewContract>(
        await apiClient.getContract(project.id, contractK.id, headers)
      );
      expect(finalK.is_hazardous_pay_rate).toBe(contractK.is_hazardous_pay_rate);
      expect(finalK.status).toBe('SCHEDULED');

      const projectAfter = getSuccessData<UrbanRenewalProject>(
        await apiClient.getProject(project.id, headers)
      );
      expect(projectAfter.community_disruption_index).toBe(projectBefore.community_disruption_index);
      expect(projectAfter.budget_balance).toBe(projectBefore.budget_balance);
    } else {
      validateErrorEnvelope(scheduleRes, { expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_BUDGET });

      const projectAfter = getSuccessData<UrbanRenewalProject>(
        await apiClient.getProject(project.id, headers)
      );
      expect(projectAfter.community_disruption_index).toBe(
        projectBefore.community_disruption_index
      );
    }
  });

  it('schedule-time dirty read: schedule K while batch proposes overlapping K′ (setup buffer)', async () => {
    const headers = buildAuthHeaders('schedule-dirty-read');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({
          project_name: 'Schedule Dirty Read',
          renovation_budget: 100_000
        }),
        headers
      )
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(
        project.id,
        createPhasePayload({ name: 'Dirty Read Phase', start_hour: 0, end_hour: 100 }),
        headers
      )
    );

    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'Dirty Read Crew', hourly_rate: 100 }),
        headers
      )
    );

    const orderK = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({ task_type: 'Task A', start_hour: 0, end_hour: 8 }),
        headers
      )
    );

    const orderKPrime = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({ task_type: 'Task B', start_hour: 8, end_hour: 16 }),
        headers
      )
    );

    const contractK = getSuccessData<CrewContract>(
      await apiClient.createContract(
        project.id,
        createContractPayload(orderK.id, crew.id),
        headers
      )
    );
    getSuccessData(await apiClient.verifySpecialization(project.id, contractK.id, headers));

    const batchPayload = {
      items: [{ work_order_id: orderKPrime.id, crew_id: crew.id }]
    };

    const [scheduleRes, batchRes] = await Promise.all([
      apiClient.scheduleWork(project.id, contractK.id, headers),
      apiClient.batchCreateContracts(project.id, batchPayload, headers),
    ]);

    if (scheduleRes.status === 200) {
      validateErrorEnvelope(batchRes, { expectedErrorId: ApiErrorId.ERR_BATCH_REJECTED });

      const finalK = getSuccessData<CrewContract>(
        await apiClient.getContract(project.id, contractK.id, headers)
      );
      expect(finalK.status).toBe('SCHEDULED');
    } else {
      expect(batchRes.status).toBe(201);
      expect([200, 409]).toContain(scheduleRes.status);
    }
  });

  it('cross-snapshot finalize vs add-crew-certification: cost immutability', async () => {
    const headers = buildAuthHeaders('finalize-vs-add-cert');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({
          project_name: 'Finalize vs Add Cert',
          renovation_budget: 100_000
        }),
        headers
      )
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(
        project.id,
        createPhasePayload({ name: 'Cert Phase', start_hour: 0, end_hour: 100 }),
        headers
      )
    );

    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'Cert Crew', hourly_rate: 100 }),
        headers
      )
    );

    const order = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'Cert Task',
          start_hour: 0,
          end_hour: 10
        }),
        headers
      )
    );

    const contract = getSuccessData<CrewContract>(
      await apiClient.createContract(
        project.id,
        createContractPayload(order.id, crew.id),
        headers
      )
    );
    getSuccessData(await apiClient.verifySpecialization(project.id, contract.id, headers));
    getSuccessData(await apiClient.scheduleWork(project.id, contract.id, headers));

    getSuccessData(await apiClient.initiateFinalAudit(project.id, headers));

    const contractBefore = getSuccessData<CrewContract>(
      await apiClient.getContract(project.id, contract.id, headers)
    );

    const [finalizeRes, certRes] = await Promise.all([
      apiClient.finalizeProject(project.id, headers),
      apiClient.addCrewCertification(
        project.id,
        crew.id,
        { specialization_name: 'ELECTRICAL', clearance_level: 2 },
        headers
      ),
    ]);

    expect(finalizeRes.status).toBe(200);
    expect(certRes.status).toBe(200);

    const finalProject = getSuccessData<UrbanRenewalProject>(
      await apiClient.getProject(project.id, headers)
    );
    expect(finalProject.status).toBe('READY_FOR_LEASING');

    const finalContract = getSuccessData<CrewContract>(
      await apiClient.getContract(project.id, contract.id, headers)
    );
    expect(finalContract.status).toBe('COMPLETED');
    expect(finalContract.final_cost).toBeDefined();

    expect(finalContract.final_cost).toBe(contractBefore.provisional_cost);

    const finalCrew = getSuccessData<RenovationCrew>(
      await apiClient.getCrew(project.id, crew.id, headers)
    );
    expect(finalCrew.crew_certifications).toContainEqual(
      expect.objectContaining({
        specialization_name: 'ELECTRICAL',
        clearance_level: 2
      })
    );
  });
});
